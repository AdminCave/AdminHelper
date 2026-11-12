{#
 # SPDX-FileCopyrightText: 2026 Kevin Stenzel
 #
 # SPDX-License-Identifier: GPL-3.0-or-later
 #}
<script>
    $(document).ready(function() {
        mapDataToFormUI({'frm_general_settings': "/api/adminhelper/general/get"}).done(function() {
            $('.selectpicker').selectpicker('refresh');
        });

        // Every value goes in as text: the server's address comes from the agent's files.
        function showInfo() {
            ajaxGet("/api/adminhelper/service/info", {}, function(data) {
                var none = "{{ lang._('none') }}";
                var yes = "{{ lang._('yes') }}";
                var no = "{{ lang._('no') }}";
                var tunnel = {
                    'none': none,
                    'running': "{{ lang._('running') }}",
                    'stopped': "{{ lang._('stopped') }}"
                };
                $("#info_registered").text(data['registered'] ? yes : no);
                $("#info_server").text(data['server'] || none);
                $("#info_version").text(data['version'] || none);
                $("#info_scheduled").text(data['scheduled'] ? yes : no);
                $("#info_tunnel").text(tunnel[data['tunnel']] || none);
                $("#info_last_run").text(data['last_run'] ? new Date(data['last_run'] * 1000).toLocaleString() : none);
            });
        }
        showInfo();

        $("#saveAct").click(function() {
            saveFormToEndpoint("/api/adminhelper/general/set", 'frm_general_settings', function() {
                $("#saveAct_progress").addClass("fa fa-spinner fa-pulse");
                ajaxCall("/api/adminhelper/service/reconfigure", {}, function(data, status) {
                    $("#saveAct_progress").removeClass("fa fa-spinner fa-pulse");
                    if (status != "success" || data['status'] != 'ok') {
                        BootstrapDialog.show({
                            type: BootstrapDialog.TYPE_WARNING,
                            title: "{{ lang._('AdminHelper') }}",
                            message: data['status_msg'] ? data['status_msg'] : "{{ lang._('The switch could not be applied.') }}",
                            draggable: true
                        });
                    }
                    showInfo();
                });
            });
        });
    });
</script>

<div class="content-box" style="padding-bottom: 1.5em;">
    {{ partial("layout_partials/base_form", ['fields': generalForm, 'id': 'frm_general_settings']) }}
    <div class="col-md-12">
        <hr />
        <button class="btn btn-primary" id="saveAct" type="button"><b>{{ lang._('Save') }}</b> <i id="saveAct_progress"></i></button>
    </div>
</div>

<div class="content-box">
    <table class="table table-striped opnsense_standard_table_form">
        <thead>
            <tr><th colspan="2">{{ lang._('Agent') }}</th></tr>
        </thead>
        <tbody>
            <tr><td style="width: 22%">{{ lang._('Registered') }}</td><td id="info_registered"></td></tr>
            <tr><td>{{ lang._('Server') }}</td><td id="info_server"></td></tr>
            <tr><td>{{ lang._('Agent version') }}</td><td id="info_version"></td></tr>
            <tr><td>{{ lang._('Scheduled') }}</td><td id="info_scheduled"></td></tr>
            <tr><td>{{ lang._('Tunnel client') }}</td><td id="info_tunnel"></td></tr>
            <tr><td>{{ lang._('Last monitoring run') }}</td><td id="info_last_run"></td></tr>
        </tbody>
    </table>
</div>
