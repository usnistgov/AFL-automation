var queueTasks = []; // array for queued tasks

class Task {
    constructor(position, info) {
        this.position = position;
        this.info = info;

        var name = this.info.task.task_name;
        var uuid = this.info.uuid;
        var checkbox = '<input type="checkbox" id="'+uuid+'_check" name="'+name+'_check"><label for="'+name+'_check">['+this.position+'] '+name+' (UUID: '+uuid+')</label>';
        var moveToFirstBtn = '<button onclick="">Move to First</button>';
        var moveToLastBtn = '<button onclick="">Move to Last</button>';
        var moveUpBtn = '<button onclick="">+</button>';
        var moveDownBtn = '<button onclick="">-</button>';
        var numInput = '<label for="'+name+'_num">Move to position: </label><input type="number" id="'+uuid+'_num" name="'+name+'_num" min="0">';
        var numInputBtn = '<button onclick="moveTaskPos(\''+uuid+'\')">Enter</button>';
        this.html = '<div id="'+uuid+'">'+checkbox+'<br>'+numInput+numInputBtn+'<br>'+moveUpBtn+moveDownBtn+moveToFirstBtn+moveToLastBtn+'<hr></div>';

        queueTasks.push(this);
        console.log(queueTasks);
    }

    }
}

// TODO complete the editQueue function
function editQueue(serverKey) {
    var server = getServer(serverKey);

    // pause the server
    server.getQueueState(function(result){
        console.log(result);
        if(result != 'Paused') {
            server.pause();
        }
    });

    // setup the queue editor w/ the server key
    server.getQueue(function(result) {
        for(let i in result[2]) {
            var tempTask = new Task(i, result[2][i]);
            console.log(tempTask);
        }

        var editorControls = '<button onclick="closeQueueEditor()" style="float:right;">x</button>';

        var tasks = '';
        for(let i in queueTasks) {
            tasks += queueTasks[i].html;
        }

        var content = editorControls + tasks;
        $('#queueEditor').html(content);
    });

    // display the queue editor w/ the popup background
    $('#queueEditor').css('visibility', 'visible');
    $('#popup-background').css('visibility', 'visible');
}

function closeQueueEditor() {
    queueTasks = []; // clears all tasks from queueTasks

    // hide the queue editor w/ the popup background
    $('#queueEditor').css('visibility', 'hidden');
    $('#popup-background').css('visibility', 'hidden');
    $('#queueEditor').empty();
}

function moveTaskPos(taskID) {
    var id = '#'+taskID+'_num';
    var pos = $(id).val();
    console.log(pos);

    if(pos < queueTasks.length-1) {
        console.log('valid');
        for(let i in queueTasks) {
            if(queueTasks[i].info.uuid == taskID) {
                console.log(queueTasks[i]);
                queueTasks[i].movePosition(pos);
            }
        }
    } else {
        console.log('invalid position');
    }
}