// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// The sql sensor asks a database server of this host how it fares, with a query the agent holds: the
// monitoring service picks one by name and never sends SQL. It logs in over the local socket as the
// admin does, with the client the server ships: MariaDB as root (unix_socket), PostgreSQL as the user
// postgres (peer). Never over TCP: a MariaDB that counts failed connections of a host locks it out.
func init() {
	sensors["sql"] = sqlSensor
}

const (
	// sqlConnectTimeoutS caps how long a client waits for its server.
	sqlConnectTimeoutS = 5
	// pgStatementTimeout and mariadbStatementTimeoutS cap a query on the server; one the client gave up
	// on would run on.
	pgStatementTimeout       = "5s"
	mariadbStatementTimeoutS = 5
)

// sqlHere says whether the sql sensor runs on this platform: on Linux alone; a seam for the tests.
var sqlHere = runtime.GOOS == "linux"

// mariadbQueries are the queries of the sql sensor for MariaDB.
var mariadbQueries = map[string]string{
	"ping": "SELECT 1 AS ok",
	"connections": "SELECT VARIABLE_VALUE AS connections, @@GLOBAL.max_connections AS max_connections " +
		"FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'THREADS_CONNECTED'",
	// One row per replication source; none on a server that is no replica.
	"replication": "SHOW ALL SLAVES STATUS",
	"size":        "SELECT COALESCE(SUM(DATA_LENGTH + INDEX_LENGTH), 0) AS size_bytes FROM information_schema.TABLES",
	// Both counted since the server started; the monitoring service takes their growth.
	"errors": "SELECT (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'ABORTED_CONNECTS') " +
		"AS aborted_connects, (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS " +
		"WHERE VARIABLE_NAME = 'CONNECTION_ERRORS_MAX_CONNECTIONS') AS connection_errors_max_connections",
	// The wsrep status variables exist without Galera too (Disconnected, OFF, 0): wsrep_on tells.
	"galera": "SELECT (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_VARIABLES WHERE VARIABLE_NAME = 'WSREP_ON') " +
		"AS wsrep_on, (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'WSREP_CLUSTER_STATUS') " +
		"AS cluster_status, (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'WSREP_READY') " +
		"AS ready, (SELECT VARIABLE_VALUE FROM information_schema.GLOBAL_STATUS WHERE VARIABLE_NAME = 'WSREP_CLUSTER_SIZE') " +
		"AS cluster_size",
}

// postgresQueries are the queries of the sql sensor for PostgreSQL; each answers one row.
var postgresQueries = map[string]string{
	"ping": "SELECT 1",
	"connections": "SELECT count(*) FILTER (WHERE backend_type = 'client backend'), " +
		"current_setting('max_connections')::int FROM pg_stat_activity",
	// The WAL receiver's status is 'streaming' while it receives (its main state in the source; the
	// documentation lists none). A replica that replayed all it received lags 0, else by the time
	// since the last transaction it replayed; it has none yet: NULL.
	"replication": "SELECT pg_is_in_recovery(), " +
		"EXISTS (SELECT 1 FROM pg_stat_wal_receiver WHERE status = 'streaming'), " +
		"CASE WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() THEN 0 " +
		"ELSE GREATEST(0, floor(extract(epoch FROM now() - pg_last_xact_replay_timestamp())))::bigint END",
	"size": "SELECT sum(pg_database_size(oid))::bigint FROM pg_database",
	// The transactions a database is from wraparound (it stops writing at 2^31 minus a reserve).
	"xid_age": "SELECT max(age(datfrozenxid))::bigint FROM pg_database",
	// Transactions of clients open for more than an hour, which hold back VACUUM.
	"long_tx": "SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' " +
		"AND xact_start < now() - interval '1 hour'",
}

// sqlQueryNames are the names of every query of either engine.
var sqlQueryNames = []string{"connections", "errors", "galera", "long_tx", "ping", "replication", "size", "xid_age"}

// errNoReplica: the server answered that it replicates from nowhere.
var errNoReplica = fmt.Errorf("%w: this database server is no replica", ErrUnsupported)

// sqlSensor runs the query of p against the database server of its engine and returns ok, the time
// the query took and what it read.
func sqlSensor(ctx context.Context, p Probe, _ string) (map[string]any, error) {
	if err := noTarget(p); err != nil {
		return nil, err
	}
	if err := knownParams(p, "engine", "query"); err != nil {
		return nil, err
	}
	engine, err := choiceParam(p, "engine", "", "mariadb", "postgres")
	if err != nil {
		return nil, err
	}
	query, err := choiceParam(p, "query", "", sqlQueryNames...)
	if err != nil {
		return nil, err
	}
	if engine == "mariadb" && mariadbQueries[query] == "" || engine == "postgres" && postgresQueries[query] == "" {
		return nil, fmt.Errorf("%w: engine %s has no query %s", ErrInvalid, engine, query)
	}
	if !sqlHere {
		return nil, fmt.Errorf("%w: the sql sensor runs on Linux hosts", ErrUnsupported)
	}
	began := time.Now()
	var values map[string]any
	if engine == "mariadb" {
		values, err = askMariaDB(ctx, query)
	} else {
		values, err = askPostgres(ctx, query)
	}
	if err != nil {
		return nil, err
	}
	values["ok"] = true
	values["duration_ms"] = time.Since(began).Milliseconds()
	return values, nil
}

// askMariaDB runs the query named query with the MariaDB client and reads its answer.
func askMariaDB(ctx context.Context, query string) (map[string]any, error) {
	// --column-names outranks a skip-column-names in the admin's option files: batchRows reads the names.
	args := []string{"--host=localhost", "--protocol=socket", "--batch", "--column-names",
		"--connect-timeout=" + strconv.Itoa(sqlConnectTimeoutS),
		"--execute=SET STATEMENT max_statement_time=" + strconv.Itoa(mariadbStatementTimeoutS) + " FOR " + mariadbQueries[query]}
	client := "mariadb"
	out, err := runTool(ctx, toolTimeout, client, args...)
	if errors.Is(err, exec.ErrNotFound) {
		// Before 10.4.6 the client is called mysql alone.
		client = "mysql"
		out, err = runTool(ctx, toolTimeout, client, args...)
	}
	if errors.Is(err, exec.ErrNotFound) {
		return nil, fmt.Errorf("%w: the MariaDB client is not installed", ErrUnsupported)
	}
	if err != nil {
		return nil, toolError(client, err)
	}
	rows := batchRows(out)
	switch query {
	case "ping":
		if len(rows) != 1 || rows[0]["ok"] != "1" {
			return nil, fmt.Errorf("%s: an answer of another form", client)
		}
		return map[string]any{}, nil
	case "connections":
		if len(rows) != 1 {
			return nil, fmt.Errorf("%s: an answer of another form", client)
		}
		return whole(client, map[string]string{
			"connections":     rows[0]["connections"],
			"max_connections": rows[0]["max_connections"],
		})
	case "replication":
		return mariadbReplication(client, rows)
	case "errors":
		if len(rows) != 1 {
			return nil, fmt.Errorf("%s: an answer of another form", client)
		}
		return whole(client, map[string]string{
			"aborted_connects":                  rows[0]["aborted_connects"],
			"connection_errors_max_connections": rows[0]["connection_errors_max_connections"],
		})
	case "galera":
		return mariadbGalera(client, rows)
	default:
		if len(rows) != 1 {
			return nil, fmt.Errorf("%s: an answer of another form", client)
		}
		return whole(client, map[string]string{"size_bytes": rows[0]["size_bytes"]})
	}
}

// mariadbReplication reads the replication of a MariaDB from its replica status, a row per source:
// running only if every source's IO and SQL thread run, its lag that of the source behind the most.
// A source that is not running has no lag (NULL); if none has one, there is no lag.
func mariadbReplication(client string, rows []map[string]string) (map[string]any, error) {
	if len(rows) == 0 {
		return nil, errNoReplica
	}
	running := true
	lag := int64(-1)
	for _, row := range rows {
		io, sql := column(row, "Slave_IO_Running", "Replica_IO_Running"), column(row, "Slave_SQL_Running", "Replica_SQL_Running")
		if io == "" || sql == "" {
			return nil, fmt.Errorf("%s: an answer of another form", client)
		}
		running = running && io == "Yes" && sql == "Yes"
		if s, err := strconv.ParseInt(column(row, "Seconds_Behind_Master", "Seconds_Behind_Source"), 10, 64); err == nil {
			lag = max(lag, s)
		}
	}
	values := map[string]any{"replication_running": running}
	if lag >= 0 {
		values["replication_lag_s"] = lag
	}
	return values, nil
}

// mariadbGalera reads the state of this node of a Galera cluster: whether it belongs to the primary
// component, whether it takes queries and how many nodes the cluster has. A server without Galera
// (wsrep_on OFF) is unsupported.
func mariadbGalera(client string, rows []map[string]string) (map[string]any, error) {
	if len(rows) != 1 {
		return nil, fmt.Errorf("%s: an answer of another form", client)
	}
	row := rows[0]
	switch row["wsrep_on"] {
	case "ON":
	case "OFF", "NULL":
		return nil, fmt.Errorf("%w: this database server runs no Galera", ErrUnsupported)
	default:
		return nil, fmt.Errorf("%s: an answer of another form", client)
	}
	size, err := strconv.ParseInt(row["cluster_size"], 10, 64)
	if err != nil || row["cluster_status"] == "" || row["ready"] != "ON" && row["ready"] != "OFF" {
		return nil, fmt.Errorf("%s: an answer of another form", client)
	}
	return map[string]any{
		"galera_primary": row["cluster_status"] == "Primary", "galera_ready": row["ready"] == "ON",
		"galera_cluster_size": size,
	}, nil
}

// column is the first of names row has, "" for none: MariaDB names some columns as MySQL renamed them.
func column(row map[string]string, names ...string) string {
	for _, name := range names {
		if v, ok := row[name]; ok {
			return v
		}
	}
	return ""
}

// batchRows reads the answer of the MariaDB client in batch mode: a line of column names, then a line per
// row, tab-separated (a tab in a value is written \t). An empty answer has no rows.
func batchRows(out []byte) []map[string]string {
	lines := strings.Split(strings.TrimRight(string(out), "\n"), "\n")
	if len(lines) < 2 {
		return nil
	}
	names := strings.Split(lines[0], "\t")
	rows := make([]map[string]string, 0, len(lines)-1)
	for _, line := range lines[1:] {
		cells := strings.Split(line, "\t")
		row := map[string]string{}
		for i, name := range names {
			if i < len(cells) {
				row[name] = cells[i]
			}
		}
		rows = append(rows, row)
	}
	return rows
}

// askPostgres runs the query named query with psql as the user postgres and reads its answer, one row
// of tab-separated values without names.
func askPostgres(ctx context.Context, query string) (map[string]any, error) {
	conn := fmt.Sprintf("dbname=postgres connect_timeout=%d application_name=adminhelper-agent "+
		"options='-c statement_timeout=%s'", sqlConnectTimeoutS, pgStatementTimeout)
	out, err := runTool(ctx, toolTimeout, "runuser", "-u", "postgres", "--", "psql", "--no-psqlrc",
		"--no-align", "--tuples-only", "--quiet", "--field-separator=\t", "--set=ON_ERROR_STOP=1",
		"--dbname="+conn, "--command="+postgresQueries[query])
	var exitErr *exec.ExitError
	switch {
	case errors.Is(err, exec.ErrNotFound):
		return nil, fmt.Errorf("%w: runuser is not installed", ErrUnsupported)
	case errors.As(err, &exitErr) && exitErr.ExitCode() == 127:
		// runuser could not find the command it was to run.
		return nil, fmt.Errorf("%w: psql is not installed", ErrUnsupported)
	case err != nil:
		return nil, toolError("psql", err)
	}
	row := strings.TrimRight(string(out), "\n")
	// A second row would otherwise run into the last cell; the checks per query below would catch
	// that only by chance.
	if strings.Contains(row, "\n") {
		return nil, errors.New("psql: an answer of another form")
	}
	cells := strings.Split(row, "\t")
	switch query {
	case "ping":
		if len(cells) != 1 || cells[0] != "1" {
			return nil, errors.New("psql: an answer of another form")
		}
		return map[string]any{}, nil
	case "connections":
		if len(cells) != 2 {
			return nil, errors.New("psql: an answer of another form")
		}
		return whole("psql", map[string]string{"connections": cells[0], "max_connections": cells[1]})
	case "replication":
		if len(cells) != 3 || cells[0] != "t" && cells[0] != "f" || cells[1] != "t" && cells[1] != "f" {
			return nil, errors.New("psql: an answer of another form")
		}
		if cells[0] == "f" {
			return nil, errNoReplica
		}
		values := map[string]any{"replication_running": cells[1] == "t"}
		if cells[2] != "" {
			lag, err := strconv.ParseInt(cells[2], 10, 64)
			if err != nil {
				return nil, errors.New("psql: an answer of another form")
			}
			values["replication_lag_s"] = lag
		}
		return values, nil
	default:
		if len(cells) != 1 {
			return nil, errors.New("psql: an answer of another form")
		}
		name := map[string]string{"size": "size_bytes", "xid_age": "xid_age", "long_tx": "long_transactions"}[query]
		return whole("psql", map[string]string{name: cells[0]})
	}
}

// whole reads every value of texts as a whole number; one that is none is an answer of another form.
func whole(client string, texts map[string]string) (map[string]any, error) {
	values := map[string]any{}
	for k, s := range texts {
		n, err := strconv.ParseInt(s, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("%s: an answer of another form", client)
		}
		values[k] = n
	}
	return values, nil
}
