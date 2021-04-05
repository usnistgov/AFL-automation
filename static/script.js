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
    addStatusBtn = '<li><button id="'+addStatusBtnID+'" onclick="addStatusDiv(\''+addStatusBtnID+'\')" class="add-status-btn" serverKey="'+server.key+'">Add Status</button></li>';
    
    addControlsBtnID = server.key+'_addControlsBtn';
    addControlsBtn = '<li><button id="'+addControlsBtnID+'" onclick="addControlsDiv(\''+addControlsBtnID+'\')" class="add-controls-btn" serverKey="'+server.key+'">Add Controls</button></li>';
    
    addQueueBtnID = server.key+'_addQueueBtn';
    addQueueBtn = '<li><button id="'+addQueueBtnID+'" onclick="addQueueDiv(\''+addQueueBtnID+'\')" class="add-queue-btn" serverKey="'+server.key+'">Add Queue</button></li>';
    
    queuedCommands = '<li class="parent"><a href="#">Queued Commands >></a><ul class="child">';
    // TODO for loop to add the queued commands from the server
    server.getQueuedCommands(function(result) {
        //console.log(result);
        for(let key in result) {
            console.log(key + ' is ' + result[key]['doc']);
        }
    });
    queuedCommands += '</ul></li>'

    unqueuedCommands = '<li class="parent"><a href="#">Unqueued Commands >></a><ul class="child">';
    // TODO for loop to add the unqueued commands from the server
    server.getUnqueuedCommands();
    unqueuedCommands += '</ul></li>'

    // TODO add the queued and unqueued sections to the menu
    child = '<ul class="child">'+addStatusBtn+addControlsBtn+addQueueBtn+'</ul>';
    id = '#'+server.key;
    $(id).append(child);
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