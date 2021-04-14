var numOfServers = 0; // counter for the number of Server objects made
var servers = []; // array for the Server objects

// TODO finish the server class
class Server {
    constructor(address) {
        this.address = address;
        this.key = 'S'+(++numOfServers);
        
        var addStatusBtnID = this.key+'_addStatusBtn';
        this.statusDiv = new Div(this.key,'status',addStatusBtnID);
        var addControlsBtnID = this.key+'_addControlsBtn';
        this.controlsDiv = new Div(this.key,'controls',addControlsBtnID);
        var addQueueBtnID = this.key+'_addQueueBtn';
        this.queueDiv = new Div(this.key,'queue',addQueueBtnID);

        var name;
        var link = this.address + 'get_info';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            async: false,
            success:function(result) {
                var r = JSON.parse(result);
                name = r["driver"];
            }
        });
        this.name = name;
        
        servers.push(this);
        console.log(servers);
    }

    updateDivs() {
        var key = this.key;

        if(this.statusDiv.onScreen == true) {
            // updates the status div's content
            var div = getDiv(key, 'status');
            div.updateDivContent();

            // updates the status div's color
            this.getQueueState(function(result) {
                var div = getDiv(key, 'status');
                div.updateDivColor(result);
            });
        }

        if(this.controlsDiv.onScreen == true) {
            // updates the controls div's content
            var div = getDiv(key, 'controls');
            div.updateDivContent();

            // updates the controls div's color
            this.getQueueState(function(result) {
                var div = getDiv(key, 'controls');
                div.updateDivColor(result);
            });
        }

        if(this.queueDiv.onScreen == true) {
            // updates the queue div's content
            var div = getDiv(key, 'queue');
            div.updateDivContent();

            // updates the queue div's color
            this.getQueueState(function(result) {
                var div = getDiv(key, 'queue');
                div.updateDivColor(result);
            });
        }
    }

    getQueue(success_func) {
        var link = this.address + 'get_queue';
        $.ajax({
            type:"GET",
            dataType:"json",
            url:link,
            success:success_func
        });
    }

    getQueuedCommands(success_func) {
        var link = this.address + 'get_queued_commands';
        $.ajax({
            type:"GET",
            dataType:"json",
            url:link,
            success:success_func
        });
    }

    getUnqueuedCommands(success_func) {
        var link = this.address + 'get_unqueued_commands';
        $.ajax({
            type:"GET",
            dataType:"json",
            url:link,
            success:success_func
        });
    }

    getQueueState(success_func) {
        var link = this.address + 'queue_state';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            success:success_func
        });
    }

    getInfo(success_func) {
        var link = this.address + 'get_info';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            success:success_func
        });
    }

    getDriverStatus(success_func) {
        var link = this.address + 'driver_status';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            success:success_func
        });
    }

    halt() {
        var link = this.address + 'halt';
        $.ajax({
            type:"POST",
            dataType:"text",
            url:link,
            success: function(result) {
                console.log(result);
            }
        });
    }

    clearQueue() {
        var link = this.address + 'clear_queue';
        $.ajax({
            type:"POST",
            dataType:"text",
            url:link,
            success: function(result) {
                console.log(result);
            }
        });
    }

    clearHistory() {
        var link = this.address + 'clear_history';
        $.ajax({
            type:"POST",
            dataType:"text",
            url:link,
            success: function(result) {
                console.log(result);
            }
        });
    }

    pause() {
        var link = this.address + 'pause';
    
        this.getQueueState(function(result) {
            console.log(result);
            if(result == 'Paused') {
                $.ajax({
                    type:"POST",
                    url:link,
                    data: JSON.stringify({'state':false}),
                    success: function(result) {
                        console.log(result);
                    },
                    contentType: "application/json",
                    dataType: "json"
                });
            } else {
                $.ajax({
                    type:"POST",
                    url:link,
                    data: JSON.stringify({'state':true}),
                    success: function(result) {
                        console.log(result);
                    },
                    contentType: "application/json",
                    dataType: "json"
                });
            }
        });
    }
}

function isValidURL(url) {
    var link = url + 'get_queue'; // TODO change to something else
    var isValid = false;

    
    $.ajax({
        type:"GET",
        dataType:"json",
        url:link,
        async: false,
        success:function(result) {
            isValid = true;
        },
        error:function() {
            isValid = false;
        }
    }); 
    
    return isValid;
}

/**
 * Returns the server with the key attribute of the Server object
 * @param {String} key 
 * @returns {Server object}
 */
function getServer(key) {
    for(var i=0; i<servers.length; i++) {
        if(servers[i].key == key) {
            return servers[i];
        }
    }
    console.log('Server not found');
}

/**
 * Adds a server from the info recived from the popup
 * @param {Popup object} popup 
 */
function addServer(popup) {
    var route = document.getElementById(popup.inputs[0].id).value; // the address of the server to add
    let server = new Server(route); // a new Server object created from the route

    addServerToMenu(server); // adds the menu items related to the server to the menu

    // adds divs to the page if checked by user
    var input;
    for(var i=0; i<popup.inputs.length; i++) {
        input = document.getElementById(popup.inputs[i].id);

        if(input.type == 'checkbox') {
            if(input.checked == true) {
                if(input.id == 'status') {
                    addStatusDiv(server.key);
                } else if(input.id == 'controls') {
                    // TODO fix so that the controls div includes the extra server controls
                    addControlsDiv(server.key);
                } else {
                    addQueueDiv(server.key);
                }
            }
        }
    }

    $('#popup').css('visibility', 'hidden'); // hides the popup from view
    $('#popup').empty(); // emties the popup html
}