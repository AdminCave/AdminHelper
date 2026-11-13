// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"maps"
	"reflect"
	"slices"
	"strings"
	"testing"
)

// stubSQLHere makes this host one the sql sensor runs on, or not.
func stubSQLHere(t *testing.T, here bool) {
	t.Helper()
	old := sqlHere
	sqlHere = here
	t.Cleanup(func() { sqlHere = old })
}

func sqlProbe(engine, query string) Probe {
	return Probe{ID: "chk-sql", Sensor: "sql", IntervalS: 300, TimeoutS: 10,
		Params: map[string]any{"engine": engine, "query": query}}
}

// mariadbArgs are the arguments of the MariaDB client client for the query named query.
func mariadbArgs(client, query string) []string {
	return []string{client, "--host=localhost", "--protocol=socket", "--batch", "--column-names", "--connect-timeout=5",
		"--execute=SET STATEMENT max_statement_time=5 FOR " + mariadbQueries[query]}
}

// psqlArgs are the arguments of runuser for psql and the query named query.
func psqlArgs(query string) []string {
	return []string{"runuser", "-u", "postgres", "--", "psql", "--no-psqlrc", "--no-align", "--tuples-only",
		"--quiet", "--field-separator=\t", "--set=ON_ERROR_STOP=1",
		"--dbname=dbname=postgres connect_timeout=5 application_name=adminhelper-agent options='-c statement_timeout=5s'",
		"--command=" + postgresQueries[query]}
}

// withoutDuration returns values without duration_ms, after checking it holds the time the query took.
func withoutDuration(t *testing.T, values map[string]any) map[string]any {
	t.Helper()
	if d, ok := values["duration_ms"].(int64); !ok || d < 0 {
		t.Errorf("duration_ms = %v, want the milliseconds the query took", values["duration_ms"])
	}
	rest := maps.Clone(values)
	delete(rest, "duration_ms")
	return rest
}

func TestTheSqlSensorHoldsReadQueriesPerEngine(t *testing.T) {
	want := map[string][]string{
		"mariadb":  {"connections", "errors", "galera", "ping", "replication", "size"},
		"postgres": {"connections", "long_tx", "ping", "replication", "size", "xid_age"},
	}
	var all []string
	for engine, queries := range map[string]map[string]string{"mariadb": mariadbQueries, "postgres": postgresQueries} {
		if got := slices.Sorted(maps.Keys(queries)); !reflect.DeepEqual(got, want[engine]) {
			t.Errorf("%s queries = %v, want %v", engine, got, want[engine])
		}
		all = append(all, want[engine]...)
		for name, q := range queries {
			if !strings.HasPrefix(q, "SELECT ") && !strings.HasPrefix(q, "SHOW ") {
				t.Errorf("%s query %s = %q, want a read", engine, name, q)
			}
		}
	}
	if got := slices.Compact(slices.Sorted(slices.Values(all))); !reflect.DeepEqual(got, sqlQueryNames) {
		t.Errorf("sqlQueryNames = %v, want %v", sqlQueryNames, got)
	}
}

func TestTheSqlSensorReadsMariaDB(t *testing.T) {
	stubSQLHere(t, true)
	cases := []struct {
		name, query, out string
		want             map[string]any
	}{
		{"ping", "ping", "ok\n1\n", map[string]any{"ok": true}},
		{"connections", "connections", "connections\tmax_connections\n12\t151\n",
			map[string]any{"ok": true, "connections": int64(12), "max_connections": int64(151)}},
		{"size", "size", "size_bytes\n123456789\n", map[string]any{"ok": true, "size_bytes": int64(123456789)}},
		{"a replica", "replication",
			"Connection_name\tSlave_IO_Running\tSlave_SQL_Running\tSeconds_Behind_Master\n\tYes\tYes\t3\n",
			map[string]any{"ok": true, "replication_running": true, "replication_lag_s": int64(3)}},
		{"three sources, one stopped", "replication",
			"Connection_name\tSlave_IO_Running\tSlave_SQL_Running\tSeconds_Behind_Master\n" +
				"a\tYes\tNo\tNULL\nb\tYes\tYes\t7\nc\tYes\tYes\t2\n",
			map[string]any{"ok": true, "replication_running": false, "replication_lag_s": int64(7)}},
		{"the names of MySQL", "replication",
			"Replica_IO_Running\tReplica_SQL_Running\tSeconds_Behind_Source\nYes\tYes\t0\n",
			map[string]any{"ok": true, "replication_running": true, "replication_lag_s": int64(0)}},
		{"no lag", "replication",
			"Slave_IO_Running\tSlave_SQL_Running\tSeconds_Behind_Master\nConnecting\tYes\tNULL\n",
			map[string]any{"ok": true, "replication_running": false}},
		{"errors", "errors", "aborted_connects\tconnection_errors_max_connections\n17\t3\n",
			map[string]any{"ok": true, "aborted_connects": int64(17), "connection_errors_max_connections": int64(3)}},
		{"a node of the primary component", "galera", "wsrep_on\tcluster_status\tready\tcluster_size\nON\tPrimary\tON\t3\n",
			map[string]any{"ok": true, "galera_primary": true, "galera_ready": true, "galera_cluster_size": int64(3)}},
		{"a node cut off", "galera", "wsrep_on\tcluster_status\tready\tcluster_size\nON\tnon-Primary\tOFF\t1\n",
			map[string]any{"ok": true, "galera_primary": false, "galera_ready": false, "galera_cluster_size": int64(1)}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := stubTools(t, answer{out: c.out})

			values, err := sqlSensor(context.Background(), sqlProbe("mariadb", c.query), "")

			if err != nil {
				t.Fatal(err)
			}
			if want := mariadbArgs("mariadb", c.query); !reflect.DeepEqual(*calls, [][]string{want}) {
				t.Fatalf("calls = %q, want %q", *calls, want)
			}
			if got := withoutDuration(t, values); !reflect.DeepEqual(got, c.want) {
				t.Errorf("values = %v, want %v", got, c.want)
			}
		})
	}
}

func TestTheSqlSensorReadsPostgreSQL(t *testing.T) {
	stubSQLHere(t, true)
	cases := []struct {
		name, query, out string
		want             map[string]any
	}{
		{"ping", "ping", "1\n", map[string]any{"ok": true}},
		{"connections", "connections", "7\t100\n",
			map[string]any{"ok": true, "connections": int64(7), "max_connections": int64(100)}},
		{"size", "size", "987654\n", map[string]any{"ok": true, "size_bytes": int64(987654)}},
		{"a replica", "replication", "t\tt\t42\n",
			map[string]any{"ok": true, "replication_running": true, "replication_lag_s": int64(42)}},
		{"a replica that replayed all", "replication", "t\tt\t0\n",
			map[string]any{"ok": true, "replication_running": true, "replication_lag_s": int64(0)}},
		{"a replica without a replayed transaction", "replication", "t\tf\t\n",
			map[string]any{"ok": true, "replication_running": false}},
		{"xid age", "xid_age", "214748\n", map[string]any{"ok": true, "xid_age": int64(214748)}},
		{"long transactions", "long_tx", "2\n", map[string]any{"ok": true, "long_transactions": int64(2)}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := stubTools(t, answer{out: c.out})

			values, err := sqlSensor(context.Background(), sqlProbe("postgres", c.query), "")

			if err != nil {
				t.Fatal(err)
			}
			if want := psqlArgs(c.query); !reflect.DeepEqual(*calls, [][]string{want}) {
				t.Fatalf("calls = %q, want %q", *calls, want)
			}
			if got := withoutDuration(t, values); !reflect.DeepEqual(got, c.want) {
				t.Errorf("values = %v, want %v", got, c.want)
			}
		})
	}
}

func TestTheSqlSensorOnAServerThatIsNoReplicaIsUnsupported(t *testing.T) {
	stubSQLHere(t, true)
	for engine, out := range map[string]string{"mariadb": "", "postgres": "f\tf\t\n"} {
		stubTools(t, answer{out: out})

		_, err := sqlSensor(context.Background(), sqlProbe(engine, "replication"), "")

		if !errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), "no replica") {
			t.Errorf("%s: err = %v, want unsupported: no replica", engine, err)
		}
	}
}

func TestTheSqlSensorOnAServerWithoutGaleraIsUnsupported(t *testing.T) {
	stubSQLHere(t, true)
	// The answer of MariaDB 11 and 10.5 without Galera: the status variables exist, wsrep_on is OFF.
	for name, out := range map[string]string{
		"wsrep off": "wsrep_on\tcluster_status\tready\tcluster_size\nOFF\tDisconnected\tOFF\t0\n",
		"no wsrep":  "wsrep_on\tcluster_status\tready\tcluster_size\nNULL\tNULL\tNULL\tNULL\n",
	} {
		stubTools(t, answer{out: out})

		_, err := sqlSensor(context.Background(), sqlProbe("mariadb", "galera"), "")

		if !errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), "no Galera") {
			t.Errorf("%s: err = %v, want unsupported: no Galera", name, err)
		}
	}
}

func TestTheSqlSensorFallsBackToTheClientOfOldMariaDBs(t *testing.T) {
	stubSQLHere(t, true)
	calls := stubTools(t, answer{err: notInstalled("mariadb")}, answer{out: "ok\n1\n"})

	values, err := sqlSensor(context.Background(), sqlProbe("mariadb", "ping"), "")

	if err != nil || values["ok"] != true {
		t.Fatalf("values = %v, err %v; want ok", values, err)
	}
	want := [][]string{mariadbArgs("mariadb", "ping"), mariadbArgs("mysql", "ping")}
	if !reflect.DeepEqual(*calls, want) {
		t.Errorf("calls = %q, want %q", *calls, want)
	}
}

func TestTheSqlSensorQuotesTheClientThatFailed(t *testing.T) {
	stubSQLHere(t, true)
	refused := toolExit(t, 1, "ERROR 2002 (HY000): Can't connect to local server through socket '/run/mysqld/mysqld.sock' (2)")
	down := toolExit(t, 2, "psql: error: connection to server on socket \"/run/postgresql/.s.PGSQL.5432\" failed\nmore")
	cases := []struct {
		name, engine string
		answers      []answer
		want         string
	}{
		{"mariadb", "mariadb", []answer{{err: refused}},
			"mariadb: ERROR 2002 (HY000): Can't connect to local server through socket '/run/mysqld/mysqld.sock' (2) (exit status 1)"},
		{"mysql", "mariadb", []answer{{err: notInstalled("mariadb")}, {err: refused}},
			"mysql: ERROR 2002 (HY000): Can't connect to local server through socket '/run/mysqld/mysqld.sock' (2) (exit status 1)"},
		{"psql", "postgres", []answer{{err: down}},
			"psql: error: connection to server on socket \"/run/postgresql/.s.PGSQL.5432\" failed (exit status 2)"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubTools(t, c.answers...)

			_, err := sqlSensor(context.Background(), sqlProbe(c.engine, "ping"), "")

			if err == nil || err.Error() != c.want || errors.Is(err, ErrUnsupported) {
				t.Errorf("err = %v, want the error %q", err, c.want)
			}
		})
	}
}

func TestTheSqlSensorWithoutItsToolsIsUnsupported(t *testing.T) {
	stubSQLHere(t, true)
	cases := []struct {
		name, engine string
		answers      []answer
		want         string
	}{
		{"no MariaDB client", "mariadb", []answer{{err: notInstalled("mariadb")}, {err: notInstalled("mysql")}},
			"the MariaDB client is not installed"},
		{"no runuser", "postgres", []answer{{err: notInstalled("runuser")}}, "runuser is not installed"},
		{"no psql", "postgres", []answer{{err: toolExit(t, 127, "runuser: failed to execute psql: No such file or directory")}},
			"psql is not installed"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubTools(t, c.answers...)

			_, err := sqlSensor(context.Background(), sqlProbe(c.engine, "ping"), "")

			if !errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), c.want) {
				t.Errorf("err = %v, want unsupported: %s", err, c.want)
			}
		})
	}
}

func TestTheSqlSensorRefusesAnswersOfAnotherForm(t *testing.T) {
	stubSQLHere(t, true)
	cases := []struct {
		name, engine, query, out string
	}{
		{"mariadb ping not 1", "mariadb", "ping", "ok\n0\n"},
		{"mariadb ping without rows", "mariadb", "ping", ""},
		{"mariadb connections of no number", "mariadb", "connections", "connections\tmax_connections\nabc\t151\n"},
		{"mariadb connections without a column", "mariadb", "connections", "connections\n12\n"},
		{"mariadb connections of two rows", "mariadb", "connections", "connections\tmax_connections\n1\t2\n3\t4\n"},
		{"mariadb size without rows", "mariadb", "size", ""},
		{"mariadb replication without its threads", "mariadb", "replication", "Slave_SQL_Running\nYes\n"},
		{"psql ping not 1", "postgres", "ping", "2\n"},
		{"psql ping of two rows", "postgres", "ping", "1\n1\n"},
		{"psql connections of one cell", "postgres", "connections", "7\n"},
		{"psql size without rows", "postgres", "size", ""},
		{"psql replication of no boolean", "postgres", "replication", "x\tt\t0\n"},
		{"psql replication of no lag", "postgres", "replication", "t\tt\tabc\n"},
		{"psql replication of two cells", "postgres", "replication", "t\tt\n"},
		{"mariadb errors of no number", "mariadb", "errors", "aborted_connects\tconnection_errors_max_connections\nNULL\t3\n"},
		{"mariadb errors without a column", "mariadb", "errors", "aborted_connects\n17\n"},
		{"mariadb galera of another wsrep_on", "mariadb", "galera", "wsrep_on\tcluster_status\tready\tcluster_size\n1\tPrimary\tON\t3\n"},
		{"mariadb galera of another ready", "mariadb", "galera", "wsrep_on\tcluster_status\tready\tcluster_size\nON\tPrimary\tyes\t3\n"},
		{"mariadb galera of no size", "mariadb", "galera", "wsrep_on\tcluster_status\tready\tcluster_size\nON\tPrimary\tON\tthree\n"},
		{"mariadb galera without rows", "mariadb", "galera", ""},
		{"psql xid age of no number", "postgres", "xid_age", "\n"},
		{"psql long transactions of two cells", "postgres", "long_tx", "1\t2\n"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubTools(t, answer{out: c.out})

			values, err := sqlSensor(context.Background(), sqlProbe(c.engine, c.query), "")

			if err == nil || !strings.HasSuffix(err.Error(), ": an answer of another form") ||
				errors.Is(err, ErrUnsupported) || errors.Is(err, ErrInvalid) {
				t.Errorf("values = %v, err %v; want an answer of another form", values, err)
			}
		})
	}
}

func TestTheSqlSensorRefusesParamsOfAnotherForm(t *testing.T) {
	stubSQLHere(t, true)
	cases := []struct {
		name   string
		params map[string]any
		target *Target
	}{
		{"a target", map[string]any{"engine": "mariadb", "query": "ping"}, &Target{Kind: kindLoopback, PortHint: 3306}},
		{"an unknown param", map[string]any{"engine": "mariadb", "query": "ping", "sql": "SELECT 1"}, nil},
		{"no engine", map[string]any{"query": "ping"}, nil},
		{"another engine", map[string]any{"engine": "mysql", "query": "ping"}, nil},
		{"an engine of no text", map[string]any{"engine": 1.0, "query": "ping"}, nil},
		{"no query", map[string]any{"engine": "postgres"}, nil},
		{"another query", map[string]any{"engine": "postgres", "query": "DROP TABLE t"}, nil},
		{"a query of PostgreSQL for MariaDB", map[string]any{"engine": "mariadb", "query": "xid_age"}, nil},
		{"a query of MariaDB for PostgreSQL", map[string]any{"engine": "postgres", "query": "galera"}, nil},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			calls := stubTools(t)
			p := Probe{ID: "chk-sql", Sensor: "sql", TimeoutS: 10, Params: c.params, Target: c.target}

			_, err := sqlSensor(context.Background(), p, "")

			if !errors.Is(err, ErrInvalid) || len(*calls) != 0 {
				t.Errorf("err = %v after %d calls, want invalid before a client", err, len(*calls))
			}
		})
	}
}

func TestTheSqlSensorRunsOnLinuxAlone(t *testing.T) {
	stubSQLHere(t, false)
	calls := stubTools(t)

	_, err := sqlSensor(context.Background(), sqlProbe("postgres", "ping"), "")

	if !errors.Is(err, ErrUnsupported) || len(*calls) != 0 {
		t.Errorf("err = %v after %d calls, want unsupported before a client", err, len(*calls))
	}
}

// TestEveryQueryOfTheSqlSensorIsOnTheAllowlist runs each query of both engines, and of both MariaDB
// clients, into a stub that checks the call against the command allowlist (stubTools): a query added
// to the sensor alone would be refused on the host.
func TestEveryQueryOfTheSqlSensorIsOnTheAllowlist(t *testing.T) {
	stubSQLHere(t, true)
	failed := answer{err: errors.New("stub")}
	for _, query := range slices.Sorted(maps.Keys(mariadbQueries)) {
		calls := stubTools(t, answer{err: notInstalled("mariadb")}, failed)
		_, _ = sqlSensor(context.Background(), sqlProbe("mariadb", query), "")
		if want := [][]string{mariadbArgs("mariadb", query), mariadbArgs("mysql", query)}; !reflect.DeepEqual(*calls, want) {
			t.Errorf("mariadb %s: calls = %q, want %q", query, *calls, want)
		}
	}
	for _, query := range slices.Sorted(maps.Keys(postgresQueries)) {
		calls := stubTools(t, failed)
		_, _ = sqlSensor(context.Background(), sqlProbe("postgres", query), "")
		if want := [][]string{psqlArgs(query)}; !reflect.DeepEqual(*calls, want) {
			t.Errorf("postgres %s: calls = %q, want %q", query, *calls, want)
		}
	}
}
