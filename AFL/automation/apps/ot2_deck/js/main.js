var token = null;

async function login() {
    if (token) return token;
    const response = await fetch('/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username:'dashboard', password:'domo_arigato'})
    });
    if (!response.ok) { alert('Login failed'); throw new Error('login'); }
    const data = await response.json();
    token = data.token;
    return token;
}

const labwareChoices = (window.OT2DeckData && window.OT2DeckData.labwareChoices) || {};

function showLabwareOptions(slot) {
    var select = $('<select></select>');
    Object.entries(labwareChoices).forEach(function(entry) {
        var key = entry[0];
        var value = entry[1];
        select.append($('<option>').attr('value', key).text(value));
    });
    $('<div></div>').append(select).dialog({
        title: 'Load labware or module in slot ' + slot,
        modal: true,
        buttons: {
            'Load': function() {
                var lw = select.val();
                var isHeaterShaker = (lw === 'heaterShakerModuleV1');
                var task = isHeaterShaker ? 'load_module' : 'load_labware';
                login().then(function(tok) {
                    $.ajax({
                        type:'POST',
                        url:'/enqueue',
                        headers: {'Content-Type':'application/json','Authorization':'Bearer '+tok},
                        data: JSON.stringify({task_name:task, name: lw, slot: slot}),
                        success: function() { setTimeout(function() { location.reload(); }, 500); },
                        error: function(xhr) { alert('Error: '+xhr.responseText); }
                    });
                });
                $(this).dialog('destroy').remove();
            },
            'Cancel': function() { $(this).dialog('destroy').remove(); }
        }
    });
}

function resetTipracks(mount) {
    login().then(function(tok) {
        $.ajax({
            type:'POST',
            url:'/enqueue',
            headers:{'Content-Type':'application/json','Authorization':'Bearer '+tok},
            data: JSON.stringify({task_name:'reset_tipracks', mount: mount}),
            success: function() { location.reload(); },
            error: function(xhr) { alert('Error: '+xhr.responseText); }
        });
    });
}

function openPrepTargetDialog(slot, targets) {
    var wells = targets.split(',').map(function(t){ return t.replace(/^\d+/, ''); });
    var rows = [];
    var cols = [];
    wells.forEach(function(w){
        var m = w.match(/([A-Za-z]+)(\d+)/);
        if(!m) return;
        if(rows.indexOf(m[1]) === -1) rows.push(m[1]);
        var c = parseInt(m[2]);
        if(cols.indexOf(c) === -1) cols.push(c);
    });
    rows.sort();
    cols.sort(function(a,b){ return a-b; });
    var table = $('<table class="well-select-table"></table>');
    var header = $('<tr><th></th></tr>');
    cols.forEach(function(c){ header.append('<th class="col-header" data-col="'+c+'">'+c+'</th>'); });
    table.append(header);
    rows.forEach(function(r){
        var row = $('<tr></tr>');
        row.append('<th class="row-header" data-row="'+r+'">'+r+'</th>');
        cols.forEach(function(c){
            var cell = $('<td class="well-cell" data-row="'+r+'" data-col="'+c+'" data-well="'+slot+r+c+'"></td>');
            row.append(cell);
        });
        table.append(row);
    });
    table.on('click','.well-cell',function(){ $(this).toggleClass('selected'); });
    table.on('click','.row-header',function(){
        var r=$(this).data('row');
        var cells=table.find('.well-cell[data-row="'+r+'"]');
        var sel=cells.filter('.selected').length===cells.length;
        cells.toggleClass('selected', !sel);
    });
    table.on('click','.col-header',function(){
        var c=$(this).data('col');
        var cells=table.find('.well-cell[data-col="'+c+'"]');
        var sel=cells.filter('.selected').length===cells.length;
        cells.toggleClass('selected', !sel);
    });
    var controls = $('<div style="text-align:center;margin-bottom:6px;"></div>');
    var selectAll = $('<button>Select All</button>').click(function(){
        table.find('.well-cell').addClass('selected');
    });
    var deselectAll = $('<button>Deselect All</button>').click(function(){
        table.find('.well-cell').removeClass('selected');
    });
    controls.append(selectAll).append(' ').append(deselectAll);
    var dialog = $('<div></div>').append(controls).append(table).dialog({
        title: 'Manage Prep Targets',
        modal:true,
        width:'auto',
        buttons:{
            'Append': function(){
                var list=table.find('.well-cell.selected').map(function(){return $(this).data('well');}).get();
                if(list.length===0){ alert('Select at least one well'); return; }
                appendPrepTargets(list.join(','));
                dialog.dialog('destroy').remove();
            },
            'Redefine': function(){
                var list=table.find('.well-cell.selected').map(function(){return $(this).data('well');}).get();
                if(list.length===0){ alert('Select at least one well'); return; }
                setPrepTargets(list.join(','));
                dialog.dialog('destroy').remove();
            },
            'Cancel': function(){ dialog.dialog('destroy').remove(); }
        }
    });
}

function appendPrepTargets(targets) {
    var t = targets.split(',');
    login().then(function(tok) {
        $.ajax({
            type:'POST',
            url:'/enqueue',
            headers:{'Content-Type':'application/json','Authorization':'Bearer '+tok},
            data: JSON.stringify({task_name:'add_prep_targets', targets: t, reset:false}),
            success: function() { location.reload(); },
            error: function(xhr) { alert('Error: '+xhr.responseText); }
        });
    });
}

function setPrepTargets(targets) {
    var t = targets.split(',');
    login().then(function(tok) {
        $.ajax({
            type:'POST',
            url:'/enqueue',
            headers:{'Content-Type':'application/json','Authorization':'Bearer '+tok},
            data: JSON.stringify({task_name:'add_prep_targets', targets: t, reset:true}),
            success: function() { location.reload(); },
            error: function(xhr) { alert('Error: '+xhr.responseText); }
        });
    });
}

$(document).ready(function() {
    $('#load-instrument-btn').click(function() {
        var mount = $('#mount-select').val();
        var pipette = $('#pipette-select').val();
        var tipracks = $('#tiprack-slots').val().split(',').map(function(x){return x.trim();}).filter(Boolean);
        if (!mount || !pipette) { alert('Select mount and pipette.'); return; }
        login().then(function(tok) {
            $.ajax({
                type: 'POST',
                url: '/enqueue',
                headers: {'Content-Type':'application/json','Authorization':'Bearer '+tok},
                data: JSON.stringify({task_name:'load_instrument', mount: mount, name: pipette, tip_rack_slots: tipracks}),
                success: function() { location.reload(); },
                error: function(xhr) { alert('Error: '+xhr.responseText); }
            });
        });
    });

    $('#reset-deck-btn').click(function() {
        if (!confirm('Are you sure you want to reset the entire deck?')) return;
        login().then(function(tok) {
            $.ajax({
                type: 'POST',
                url: '/enqueue',
                headers: {'Content-Type':'application/json','Authorization':'Bearer '+tok},
                data: JSON.stringify({task_name:'reset_deck'}),
                success: function() { location.reload(); },
                error: function(xhr) { alert('Error: '+xhr.responseText); }
            });
        });
    });
});
