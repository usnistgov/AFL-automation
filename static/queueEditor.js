var queueTasks = [];
class Task {
    constructor() {

    }
}

// TODO complete the editQueue function
function editQueue(serverKey) {
    console.log('Edit Queue Button was clicked.');

    // pause the server
    var server = getServer(serverKey);
    server.getQueueState(function(result){
        console.log(result);
        if(result != 'Paused') {
            server.pause();
        }
    });

    // setup the queue editor w/ the server key
    server.getQueue(function(result) {
        
    });

    // display the queue editor w/ the popup background
    $('#queueEditor').css('visibility', 'visible');
    $('#popup-background').css('visibility', 'visible');
}