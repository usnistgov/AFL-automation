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

    movePosition(newPosition) {
        console.log('moves the position to '+newPosition);
        var oldPosition = this.position;
        
    }

    moveUp() {

    }

    moveDown() {

    }

    moveToFirst() {

    }

    moveToLast() {

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

        var closeBtn = '<button onclick="closeQueueEditor()" style="float:right;">x</button>';
        var moveSelectedTopBtn = '<button onclick="">Move Selected Task(s) to Top</button>'; // TODO make the function(s) for the button
        var moveSelectedBottomBtn = '<button onclick="">Move Selected Task(s) to Bottom</button>'; // TODO make the function(s) for the button
        var moveSelectedBtn = '<label for="newTaskPos">Move Selected Task(s) to Position: </label><input type="number" id="newTaskPos" name="newTaskPos" min="0"><button onclick="">Enter</button>'; // TODO make the function(s) for the button
        var removeSelectedBtn = '<button onclick="">Remove Selected Task(s)</button>'; // TODO make the function(s) for the button
        var commitBtn = '<button onclick="">Commit Queue Edits</button>'; // TODO make the function(s) for the button
        var searchBar = '<br><input type="text" id="taskSearchBar" onkeyup="searchFilter()" placeholder="Search for tasks">';
        var editorControls = moveSelectedTopBtn+moveSelectedBottomBtn+removeSelectedBtn+searchBar+commitBtn+closeBtn+'<hr>'; 

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

function searchFilter() {
    var input = $('#taskSearchBar').val().toUpperCase();

    for(let i = 0; i<queueTasks.length; i++) {
        var taskID = '#'+queueTasks[i].info.uuid;
        if(queueTasks[i].info.task.task_name.toUpperCase().indexOf(input) > -1) {
            $(taskID).css('display','');
        } else {
            $(taskID).css('display','none');
        }
    }
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