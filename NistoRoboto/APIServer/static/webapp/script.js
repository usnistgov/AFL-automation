/**
 * Adds the menu items related to the server to the menu
 * @param {Server} server the server object to be added to the menu
 */
function addServerToMenu(server) {
    parent = '<li id="'+server.key+'" class="parent"><a href="#">'+server.name+'</a>';
    $('#servers').append(parent);

    addStatusBtnID = server.key+'_addStatusBtn';
    addStatusBtn = '<li><button id="'+addStatusBtnID+'" onclick="addStatusDiv(\''+server.key+'\')" class="add-status-btn">Add Status</button></li>';

    addControlsBtnID = server.key+'_addControlsBtn';
    addControlsBtn = '<li><button id="'+addControlsBtnID+'" onclick="addControlsDiv(\''+server.key+'\')" class="add-controls-btn">Add Controls</button></li>';

    addQueueBtnID = server.key+'_addQueueBtn';
    addQueueBtn = '<li><button id="'+addQueueBtnID+'" onclick="addQueueDiv(\''+server.key+'\')" class="add-queue-btn">Add Queue</button></li>';

    addQuickbarBtnID = server.key+'_addQuickbarBtn';
    addQuickbarBtn = '<li><button id="'+addQuickbarBtnID+'" onclick="addQuickbarDiv(\''+server.key+'\')" class="add-quickbar-btn">Add Quickbar</button></li>';

    queuedCommandsID = server.key+'_queuedCommands';
    queuedCommands = '<li class="parent"><a href="#">Queued Commands >></a><ul id="'+queuedCommandsID+'" class="child"></ul></li>';

    unqueuedCommandsID = server.key+'_unqueuedCommands';
    unqueuedCommands = '<li class="parent"><a href="#">Unqueued Commands >></a><ul id="'+unqueuedCommandsID+'" class="child"></ul></li>';

    child = '<ul class="child">'+addStatusBtn+addControlsBtn+addQueueBtn+addQuickbarBtn+queuedCommands+unqueuedCommands+'</ul>';
    id = '#'+server.key;
    $(id).append(child);

    // TODO make the queued command buttons functional on onClick event
    server.getQueuedCommands(function(result) {
        var commands = '';
        for(let key in result) {
            // console.log(key + ' is ' + result[key]['doc']);
            commands += '<li><button>'+key+'</button></li>';
        }
        id = '#'+server.key+'_queuedCommands';
        $(id).append(commands);
    });

    // TODO make the unqueued command buttons functional on onClick event
    server.getUnqueuedCommands(function(result) {
        var commands = '';
        for(let key in result) {
            // console.log(key + ' is ' + result[key]['doc']);
            commands += '<li><button>'+key+'</button></li>';
        }
        id = '#'+server.key+'_unqueuedCommands';
        $(id).append(commands);
    });

    // TODO make the unqueued command buttons functional on onClick event
    server.getQuickbar(function(result) {
      var commands = ''; 
      var button_text, params, default_value, label, button_class, python_type;
      for(let function_name in result) { 
        commands += '<div class="quickbar_group">'
        button_text = result[function_name]['qb']['button_text'];
        params = result[function_name]['qb']['params'];
        params_class = `${function_name.replaceAll(' ','_').toLowerCase()}_params`

        for(let field_name in params) {
          label = params[field_name]['label']
          commands += `<label for=${name}>${label}</label>`;

          // commands += `<li>`
          python_type = params[field_name]['type']
          default_value = params[field_name]['default']
          if((python_type=='float') | (python_type=='int') | (python_type=="text")){
            commands += `<input `
            commands += `type="text" `
            commands += `python_param="${field_name}" `
            commands += `python_type="${python_type}" `
            commands += `name="${label}" `
            commands += `class="${params_class}" `
            commands += `placeholder=${default_value} `
            commands += `>`
          } else if(python_type=='bool'){
            commands += `<input `
            commands += `type="checkbox" `
            commands += `python_param="${field_name}" `
            commands += `python_type="${python_type}" `
            commands += `name="${label}" `
            commands += `class="${params_class}" `
            commands += `>`
          } else {
            throw `Parameter type not recognized: ${params[field_name]['type']}`
          }

        }
        //commands +=`</li>`;
        // commands += "<li>";
        commands += `<div class="quickbar_button">`
        commands += `<button `
        commands += `onclick="executeQuickbarTask('${server.key}','${function_name}')">`;
        commands += `${button_text}`
        commands += "</button>";
        commands += '</div>'
        //commands +=`</li>`;
        commands += '</div>'
      }
      
      // id = '#'+server.key+'_quickbarContent'; 
      // slect the div of class content inside of the div with custom attr divType='quickbar"
      $(`#${server.key}_quickbar>div.content`).append(commands);
    });
}

/**
 * Removes the div element and re-enables the button to re-add
 * @param {Div Element} div 
 */
function closeDiv(div) {
    var serverKey = $(div).attr('serverKey');
    var divType = $(div).attr('divType');

    // gets the menu button that adds the div
    var serverMenuID = '#'+serverKey;
    var btn;
    if(divType == 'status') {
        btn = $(serverMenuID).find('button.add-status-btn');
    } else if(divType == 'controls') {
        btn = $(serverMenuID).find('button.add-controls-btn');
    } else {
        btn = $(serverMenuID).find('button.add-queue-btn');
    }

    // re-enables the menu button to add the div back
    btn.attr('disabled', false);
    btn.css('background-color', '#ED553B');
    btn.css('cursor','pointer')

    // removes the div
    div.remove();

    // updates the div's onScreen attribute
    var div2 = getDiv(serverKey, divType);
    div2.setOnScreen(false);
}

/**
 * Toggles between collasping and expanding the div element's content
 * @param {Div Element} div 
 */
function collapseDiv(div) {
    $(div).find('div.content').slideToggle(400);
    
    var currText = $(div).find('button.col_exp_btn').html();
    if(currText == 'Collapse') {
        $(div).find('button.col_exp_btn').html('Expand');
    } else {
        $(div).find('button.col_exp_btn').html('Collapse');
    }
}

/**
 * Disables the use of the button and greys it out
 * @param {Button Element} btn 
 */
function disableBtn(btn) {
    $(btn).css('background-color', 'grey');
    $(btn).attr('disabled', 'disabled');
    btn.css('cursor','default')
}

/**
 * Sets the column count
 * @param {Int} count 
 */
function setColCount(count) {
    if(count==1) {
      $('#column2').hide();
      $('#column3').hide();
      $("#column2, #column3").children(".container").each(function () {$(this).appendTo("#column1");})
    } else if(count==2){
      $('#column2').show();
      $('#column3').hide();
      $("#column3").children(".container").each(function () {$(this).appendTo("#column1");})
    } else if(count==3){
      $('#column2').show();
      $('#column3').show();
    }
}

function distributeContainers() {
    var ncols = $(".container-column:visible").length
    var nper =  parseInt($(".container-column").children(".container").length/ncols)
    var containers = $(".container-column").children(".container").toArray()
    console.log(ncols,nper)
    for (let dest_index=1;dest_index<=ncols;dest_index++){
      for (let j=0;j<nper;j++){
        console.log(`#column${dest_index} ${j}`)
        $(`#column${dest_index}`).append(containers.pop());
      }
    }

}

$(function() {
    // On event that the add-server-btn is clicked, add the add server popup
    $('#add-server-btn').click(function() {
        addServerPopup();
    });

    // Makes the divs sortable with the header class
    $("#column1, #column2, #column3").sortable({ 
      //handle: '.header', 
      connectWith:".container-column",
      cancel: '',
      placeholder: "container-placeholder"
    });

});

// check robot status every 5 seconds and adjust background color accordingly
setInterval(function(){ 
    for(let s in servers){
        servers[s].update();
    }
}, 500);
