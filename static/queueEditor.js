var queueTasks = []; // array for queued tasks

class Task {
    constructor(position, info) {
        this.ogPosition = position;
        this.position = position;
        this.info = info;
        this.selected = false;

        var name = this.info.task.task_name;
        var uuid = this.info.uuid;
        var taskLabel = '<h4 onclick="select(\''+uuid+'\')">['+this.position+'] '+name+' (UUID: '+uuid+')</h4>';
        var moveToFirstBtn = '<button onclick="">Move to First</button>'; // TODO make the function(s) for the button
        var moveToLastBtn = '<button onclick="">Move to Last</button>'; // TODO make the function(s) for the button
        var moveUpBtn = '<button onclick="">+</button>'; // TODO make the function(s) for the button
        var moveDownBtn = '<button onclick="">-</button>'; // TODO make the function(s) for the button
        var numInput = '<label for="'+name+'_num">Move to position: </label><input type="number" id="'+uuid+'_num" name="'+name+'_num" min="0">';
        var numInputBtn = '<button onclick="moveTaskPos(\''+uuid+'\')">Enter</button>';
        var metaData = '<div id="'+uuid+'_data" style="display: none;">'+JSON.stringify(this.info)+'</div>';
        var viewDataBtn = '<button onclick="toggleTaskData(\''+uuid+'\')" class="toggleTaskDataBtn">View/Close Task Meta Data</button>';
        var removeBtn = '<button onclick="">Remove Task</button>'; // TODO make the function(s) for the button
        this.html = '<div id="'+uuid+'">'+taskLabel+numInput+numInputBtn+'<br>'+moveUpBtn+moveDownBtn+moveToFirstBtn+moveToLastBtn+viewDataBtn+removeBtn+metaData+'<hr></div>';

        queueTasks.push(this);
    }

    select() {
        var id = '#'+this.info.uuid;

        if(this.selected == false) {
            this.selected = true;
            $(id).find('h4').css('color','green');
        } else {
            this.selected = false;
            $(id).find('h4').css('color','black');
        }
    }

    removeToggle() {
        if(this.position < 0) {
            var index = removedTasks.indexOf(this);
            if(index > -1) {
                removedTasks.splice(index, 1);
            }
        } else {
            this.position = -1;
            removedTasks.push(this);
        }
    }

    // TODO complete the function
    movePosition(newPosition) {
        console.log('moves the position to '+newPosition);
        var oldPosition = this.position;
        
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
            // console.dir(tempTask);
        }

        // TODO make the function(s) for the buttons for the selected task controls
        var moveSelectedBtn = '<label for="newTaskPos">Move to Position: </label><input type="number" id="newTaskPos" name="newTaskPos" min="0"><button onclick="">Enter</button>';
        var moveSelectedTopBtn = '<button onclick="">Move to Top</button>';
        var moveSelectedBottomBtn = '<button onclick="">Move to Bottom</button>';
        var removeSelectedBtn = '<button onclick="">Remove Task(s)</button>';
        var selectedControls = '<label>Selected Task(s) Controls: </label>'+moveSelectedTopBtn+moveSelectedBottomBtn+removeSelectedBtn+'<br>'+moveSelectedBtn;
        
        var closeBtn = '<button onclick="closeQueueEditor()" style="float:right;">x</button>';
        var commitBtn = '<button onclick="commitQueueEdits()">Commit Queue Edits</button>';
        var searchBar = '<label>Task Search: </label><input type="text" id="taskSearchBar" onkeyup="searchFilter()" placeholder="Search for tasks by name">';
        var editorControls = closeBtn+commitBtn+searchBar+'<br>'+selectedControls+'<hr>';

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
        alert('You entered an invalid position.');
    }
}

function toggleTaskData(taskID) {
    var id = '#'+taskID+'_data';
    $(id).slideToggle(400);
}