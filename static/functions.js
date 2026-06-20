
// Attach CSRF token to all non-safe AJAX requests
$.ajaxSetup({
    beforeSend: function(xhr, settings) {
        if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type)) {
            var token = $('meta[name="csrf-token"]').attr('content');
            if (token) {
                xhr.setRequestHeader('X-CSRFToken', token);
            }
        }
    }
});

function showProgress() {
    $('#loading_overlay').show();
    $('button, input[type="button"]').prop('disabled', true);
}

function hideProgress() {
    $('#loading_overlay').hide();
    $('button, input[type="button"]').prop('disabled', false);
}

function export_to_zenodo(){
    try {
        showProgress();
        $("#output").html('<img src="static/progress.gif" alt="progress">');
        $.ajax({
            type: "POST",
            url: "ajax",
            data: {
                action: "export_to_zenodo",
                // Zenodo API key is stored server-side after list_depositions; not re-sent here
                ckan_resource_id: $('#ckan_resource_id').val(),
                deposition_id: $('#sel_depsition option:selected').val()
            },
            success: function (data) {
                $("#output").html(data);
                hideProgress();
            },
            complete: function () {},
            error: function () {
                $("#output").html('<div style="color:red;">An unexpected error occurred. Please reload and try again.</div>');
                hideProgress();
            },
            dataType: 'text'
        });
    } catch (e) {
        hideProgress();
        alert(e);
    }
}

function create_deposit_and_export() {
    try {
        showProgress();
        $("#output").html('<img src="static/progress.gif" alt="progress">');
        $.ajax({
            type: "POST",
            url: "ajax",
            data: {
                action: "create_deposit_and_export",
                // Zenodo API key is stored server-side after list_depositions; not re-sent here
                ckan_resource_id: $('#ckan_resource_id').val(),
                deposit_name: $('#txt_deposit_name').val(),
                deposit_desc: $('#txt_deposit_desc').val(),
                upload_type: $('#sel_upload_type').val(),
                access_right: $('#sel_access_right').val(),
            },
            success: function (data) {
                $("#output").html(data);
                hideProgress();
            },
            complete: function () {},
            error: function () {
                $("#output").html('<div style="color:red;">An unexpected error occurred. Please reload and try again.</div>');
                hideProgress();
            },
            dataType: 'text'
        });
    } catch (e) {
        hideProgress();
        alert(e);
    }
}

function export_package_to_zenodo() {
    try {
        showProgress();
        $("#output").html('<img src="static/progress.gif" alt="progress">');
        $.ajax({
            type: "POST",
            url: "ajax",
            data: {
                action: "export_package_to_zenodo",
                package_id: $('#ckan_package_id').val(),
                deposition_id: $('#sel_depsition option:selected').val()
            },
            success: function (data) {
                $("#output").html(data);
                hideProgress();
            },
            complete: function () {},
            error: function () {
                $("#output").html('<div style="color:red;">An unexpected error occurred. Please reload and try again.</div>');
                hideProgress();
            },
            dataType: 'text'
        });
    } catch (e) {
        hideProgress();
        alert(e);
    }
}

function list_depositions(option) {
    try {
        showProgress();
        $("#output_step_two").html('<img src="static/progress.gif" alt="progress">');
        $.ajax({
            type: "POST",
            url: "ajax",
            data: {
                action: "list_depositions",
                zenodo_apikey: $('#inp_zenodo_apikey').val()
            },
            success: function (data) {
                $("#output_step_two").html(data);
                $('#txt_deposit_name').val($('#ckan_package_title').val());
                $('#txt_deposit_desc').val($('#ckan_package_desc').val());
                if(option === 1) {
                    $("#zenodo_deposit_1").css("display", "block");
                    $("#zenodo_deposit_2").css("display", "none");
                }
                else if(option === 2) {
                    $("#zenodo_deposit_1").css("display", "none");
                    $("#zenodo_deposit_2").css("display", "block");
                }
                $("#output").html('');
                hideProgress();
            },
            complete: function () {},
            error: function () {
                $("#output_step_two").html('<div style="color:red;">Failed to load depositions. Check your API key and try again.</div>');
                hideProgress();
            },
            dataType: 'text'
        });
    } catch (e) {
        hideProgress();
        alert(e);
    }
}

function show_popup(){
    try {
        document.getElementById("transparent_background").style.display = "block";
        document.getElementById("popup_window").style.display = "block";
        document.getElementById("popup_window").style.left = Math.round((window.innerWidth - document.getElementById('popup_window').clientWidth) / 2 + document.body.scrollLeft) + "px";
        document.getElementById("popup_window").style.top = Math.round((window.innerHeight - document.getElementById('popup_window').clientHeight - 20) / 2 + document.body.scrollTop) + "px";
    } catch (e) {
        alert(e);
    }
}

function hide_popup(){
    document.getElementById("transparent_background").style.display = "none";
    document.getElementById("popup_window").style.display = "none";
}
