var defaultServer = new Server('http://localhost:5051/'); // the default server (the server added on page load)
addServerToMenu(defaultServer); // adds the default server to the menu

/**
 * Adds the menu items related to the server to the menu
 * @param {Server} server the server object to be added to the menu
 */
function addServerToMenu(server) {
    parent = '<li id="'+server.key+'" class="parent"><a href="#">'+server.getName()+'</a>';
    $('#servers').append(parent);

    addStatusBtnID = server.key+'_addStatusBtn';
    addStatusBtn = '<li><button id="'+addStatusBtnID+'" onclick="addStatusDiv(\''+server.key+'\')" class="add-status-btn">Add Status</button></li>';

    addControlsBtnID = server.key+'_addControlsBtn';
    addControlsBtn = '<li><button id="'+addControlsBtnID+'" onclick="addControlsDiv(\''+server.key+'\')" class="add-controls-btn">Add Controls</button></li>';

    addQueueBtnID = server.key+'_addQueueBtn';
    addQueueBtn = '<li><button id="'+addQueueBtnID+'" onclick="addQueueDiv(\''+server.key+'\')" class="add-queue-btn">Add Queue</button></li>';

    queuedCommandsID = server.key+'_queuedCommands';
    queuedCommands = '<li class="parent"><a href="#">Queued Commands >></a><ul id="'+queuedCommandsID+'" class="child"></ul></li>';

    unqueuedCommandsID = server.key+'_unqueuedCommands';
    unqueuedCommands = '<li class="parent"><a href="#">Unqueued Commands >></a><ul id="'+unqueuedCommandsID+'" class="child"></ul></li>';

    child = '<ul class="child">'+addStatusBtn+addControlsBtn+addQueueBtn+queuedCommands+unqueuedCommands+'</ul>';
    id = '#'+server.key;
    $(id).append(child);

    queuedCommands += server.getQueuedCommands(function(result) {
        var commands = '';
        for(let key in result) {
            // console.log(key + ' is ' + result[key]['doc']);
            commands += '<li><button>'+key+'</button></li>';
        }
        id = '#'+server.key+'_queuedCommands';
        $(id).append(commands);
    });

    server.getUnqueuedCommands(function(result) {
        var commands = '';
        for(let key in result) {
            // console.log(key + ' is ' + result[key]['doc']);
            commands += '<li><button>'+key+'</button></li>';
        }
        id = '#'+server.key+'_unqueuedCommands';
        $(id).append(commands);
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
}

/**
 * Toggles between collasping and expanding the div element's content
 * @param {Div Element} div 
 */
function collapseDiv(div) {
    $(div).find('div.content').slideToggle(400);
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

$(function() {
    // On event that the add-server-btn is clicked, add the add server popup
    $('#add-server-btn').click(function() {
        addServerPopup();
    });

    // Makes the divs sortable with the header class
    $("#containers").sortable({ handle: '.header', cancel: ''});
});

// check robot status every 5 seconds and adjust background color accordingly
// setInterval(function(){ 
//     console.log('checked');
        // check servers states and adjust background color accordingly
// }, 5000);