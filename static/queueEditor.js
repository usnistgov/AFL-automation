var queueTasks = []; // array for queued tasks
var removedTasks = [];

class Task {
    constructor(position, info) {
        this.ogPosition = position;
        this.position = position;
        this.info = info;
        this.selected = false;

        var name = this.info.task.task_name;
        var uuid = this.info.uuid;
        var taskLabel = '<h4 onclick="select(\''+uuid+'\')">[<span class="taskPos">'+this.position+'</span>] '+name+' (UUID: '+uuid+')</h4>';
        var moveToFirstBtn = '<button onclick="">Move to First</button>'; // TODO make the function(s) for the button
        var moveToLastBtn = '<button onclick="">Move to Last</button>'; // TODO make the function(s) for the button
        var moveUpBtn = '<button onclick="">+</button>'; // TODO make the function(s) for the button
        var moveDownBtn = '<button onclick="">-</button>'; // TODO make the function(s) for the button
        var numInput = '<label for="'+name+'_num">Move to position: </label><input type="number" id="'+uuid+'_num" name="'+name+'_num" min="0">';
        var numInputBtn = '<button onclick="moveTaskPos(\''+uuid+'\')">Enter</button>';
        var metaData = '<div id="'+uuid+'_data" style="display: none;">'+JSON.stringify(this.info)+'</div>';
        var viewDataBtn = '<button onclick="toggleTaskData(\''+uuid+'\')" class="toggleTaskDataBtn">Task Meta Data</button>';
        var removeBtn = '<button onclick="">Remove Task</button>'; // TODO make the function(s) for the button
        this.html = '<div id="'+uuid+'">'+taskLabel+numInput+numInputBtn+'<br>'+moveUpBtn+moveDownBtn+moveToFirstBtn+moveToLastBtn+viewDataBtn+removeBtn+metaData+'<hr></div>';

        queueTasks.push(this);
    }

    select() {
        var id = '#'+this.info.uuid;

        if(this.selected == false) {
            this.selected = true;
            $(id).find('h4').css('color','blue');
        } else {
            this.selected = false;
            $(id).find('h4').css('color','black');
        }
    }

    // TODO test this function
    removeToggle() {
        if(this.position < 0) {
            var index = removedTasks.indexOf(this);
            if(index > -1) {
                queueTasks.push(removedTasks.splice(index, 1));
                // TODO change the task label position to reflect it's re-added
                console.log(removedTasks);
            }
        } else {
            this.position = -1;
            removedTasks.push(this);
            // TODO change the task label position to - to reflect it's removed
        }
    }

    setPosition(pos) {
        if(this.position != pos) {
            this.position = pos; // sets the new task position
        
            var div = '#'+this.info.uuid;
            $(div).find('.taskPos').html(pos); // changes the task label to display the new position
        }
    }

    movePosition(newPosition) {
        console.log('moves the position to '+newPosition);

        var task = queueTasks.splice(this.position,1);
        var temp = queueTasks.splice(newPosition);
        queueTasks.push(task[0]);
        queueTasks = queueTasks.concat(temp);

        for(let i in queueTasks) {
            queueTasks[i].setPosition(i);
        }

        console.log(queueTasks);

        // reorders the display order of the tasks
        var taskDivID = '#'+this.info.uuid;
        if(newPosition == 0) {
            var nextTaskDivID = '#'+queueTasks[1].info.uuid;
            $(taskDivID).insertBefore(nextTaskDivID);
        } else {
            var prevTaskDivID = '#'+queueTasks[newPosition-1].info.uuid;
            $(taskDivID).insertAfter(prevTaskDivID);
        }
    }
}

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
        var moveSelectedBtn = '<label for="newTaskPos">Move to Position: </label><input type="number" id="newTaskPos" name="newTaskPos" min="0"><button onclick="moveSelected(\'m\')">Enter</button>';
        var moveSelectedTopBtn = '<button onclick="moveSelected(\'t\')">Move to Top</button>';
        var moveSelectedBottomBtn = '<button onclick="moveSelected(\'b\')">Move to Bottom</button>';
        var removeSelectedBtn = '<button onclick="">Remove Task(s)</button>';
        var selectedControls = '<label>Selected Task(s) Controls: </label>'+moveSelectedTopBtn+moveSelectedBottomBtn+removeSelectedBtn+'<br>'+moveSelectedBtn;
        
        var closeBtn = '<button onclick="closeQueueEditor()" style="float:right;">x</button>';
        var commitBtn = '<button onclick="commitQueueEdits()">Commit Queue Edits</button>';
        var searchBar = '<label>Task Search: </label><input type="text" id="taskSearchBar" onkeyup="searchFilter()" placeholder="Search for tasks by name">';
        var editorControls = '<div id="queueEditorControls" style="background-color:lightgrey;">'+closeBtn+commitBtn+searchBar+'<br>'+selectedControls+'<hr></div>';

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

/**
 * Selects the given task
 * @param {String} taskID 
 */
function select(taskID) {
    for(let i = 0; i<queueTasks.length; i++) {
        if(queueTasks[i].info.uuid == taskID) {
            queueTasks[i].select();
        }
    }
}

/**
 * (incomplete) Moves selected tasks to the top, the bottom, or to a specified position in the queue editor
 * @param {String} place 
 */
function moveSelected(place) {
    var selected = [];
    for(let i in queueTasks) {
        if(queueTasks[i].selected) {
            selected.push(queueTasks[i]);
        }
    }
    console.log(selected);
    
    var pos;
    if(place == "t") { // move to top
        pos = 0;
        for(let i in selected) {
            selected[i].movePosition(pos);
            pos++;
        }
    } else if(place == "b") { // move to bottom
        pos = queueTasks.length-1;
        for(let i in selected) {
            selected[i].movePosition(pos);
        }
    } else { // move to specified position
        pos = $('#newTaskPos').val();
        console.log('move to '+pos);
        // TODO move selected tasks to pos
        // for(let i in selected) {
        //     selected[i].movePosition(pos);
        //     pos++;
        // }
    }
}

/**
 * Closes the queue editor
 */
function closeQueueEditor() {
    queueTasks = []; // clears all tasks from queueTasks

    // hide the queue editor w/ the popup background
    $('#queueEditor').css('visibility', 'hidden');
    $('#popup-background').css('visibility', 'hidden');
    $('#queueEditor').empty();
}

/**
 * Filters the tasks shown in the queue editor based on the search bar input
 */
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

/**
 * (incomplete) Changes the position of the given task in the queuedTasks array
 * @param {String} taskID 
 */
function moveTaskPos(taskID) {
    var id = '#'+taskID+'_num';
    var pos = $(id).val();
    console.log(pos);

    if(pos < queueTasks.length) {
        console.log('valid position');

        var notMoved = true;
        var index = 0;
        while(notMoved) {
            if(queueTasks[index].info.uuid == taskID) {
                console.log(queueTasks[index]);
                queueTasks[index].movePosition(pos);
                notMoved = false;
            }

            if(index > (queueTasks.length-1)) {
                alert('Error: task not found.');
            }

            index++;
        }
    } else {
        alert('Error: You entered an invalid position.');
    }
}

/**
 * Displays/Hides task's meta data within the queue editor
 * @param {String} taskID 
 */
function toggleTaskData(taskID) {
    var id = '#'+taskID+'_data';
    $(id).slideToggle(400);
}