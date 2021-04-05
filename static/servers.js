var numOfServers = 0; // counter for the number of Server objects made
var servers = []; // array for the Server objects

// TODO finish the server class
class Server {
    constructor(address) {
        this.address = address;
        this.key = 'S'+(++numOfServers);
        servers.push(this);
        console.log(servers);
    }

    /**
     * Returns the name of the server
     * @returns the name of the server
     */
    getName() {
        return this.address;
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
            dataType:"json",
            url:link,
            success:success_func
        });
    }
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

    // prints the popup's input results to the console
    for(var i=0; i<popup.inputs.length; i++) {
        if(popup.inputs[i].type == 'checkbox') {
            console.log(document.getElementById(popup.inputs[i].id).checked);
        }
        if(popup.inputs[i].type == 'text') {
            console.log(document.getElementById(popup.inputs[i].id).value);
        }
        if(popup.inputs[i].type == 'number') {
            // TODO check if this works
            console.log(document.getElementById(popup.inputs[i].id).value);
        }
    }

    $('#popup').css('visibility', 'hidden'); // hides the popup from view
    $('#popup').empty(); // emties the popup html
}