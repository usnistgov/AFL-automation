var queueTasks = []; // array for queued tasks
var removedTasks = [];

class Task {
    constructor(position, info) {
        this.ogPosition = position;
        this.position = position;
        this.info = info;
        this.selected = false;
        this.removed = false;

        var name = this.info.task.task_name;
        var uuid = this.info.uuid;
        var taskLabel = '<h4 onclick="select(\''+uuid+'\')">[<span class="taskPos">'+this.position+'</span>] '+name+' (UUID: '+uuid+')</h4>';
        var moveUpBtn = '<button onclick="">+</button>'; // TODO make the function(s) for the button
        var moveDownBtn = '<button onclick="">-</button>'; // TODO make the function(s) for the button
        var metaData = '<div id="'+uuid+'_data" style="display: none;">'+JSON.stringify(this.info)+'</div>';
        var viewDataBtn = '<button onclick="toggleTaskData(\''+uuid+'\')" class="toggleTaskDataBtn">&#x1F6C8;</button>';
        this.html = '<div id="'+uuid+'">'+taskLabel+moveUpBtn+moveDownBtn+viewDataBtn+metaData+'<hr></div>';

        queueTasks.push(this);
    }

    select() {
        var id = '#'+this.info.uuid;

        if(this.removed == false) {
            if(this.selected == false) {
                this.selected = true;
                $(id).css('background-color','green');
            } else {
                this.selected = false;
                $(id).css('background-color','white');
            }
        }
    }

    remove() {
        var div = '#'+this.info.uuid;
        if(this.removed = false) {
            this.removed = true;
            removedTasks.push(queueTasks.splice(this.position,1)); // removes the task from queueTasks and moves it to removedTasks
            this.position = -1;    
            $(div).find('.taskPos').html('-'); // changes the task label position to - to reflect it's removed
            // TODO move task div somewhere and/or indicate that the task is removed in editor
        } else {
            this.removed = false;
            queueTasks.push(this);
            var pos = queueTasks.length-1;
            this.position = pos;
            $(div).find('.taskPos').html(pos);
            // TODO move task div to bottom
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
        var editorControls = '<div id="queueEditorControls">'+closeBtn+commitBtn+searchBar+'<br>'+selectedControls+'</div><hr style="margin-top:80px;">';

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

        var spaceAvailable = queueTasks.length - pos;
        if(selected.length <= spaceAvailable) {
            for(let i in selected) {
                selected[i].movePosition(queueTasks.length-1);
            }

            for(let i in selected) {
                console.dir(selected[i]);
                console.log(pos);
                selected[i].movePosition(pos);
                pos++;
            }
        } else {
            alert('Error: cannot make this edit (more tasks than spaces available at that position in the queue)');
        }
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
 * Displays/Hides task's meta data within the queue editor
 * @param {String} taskID 
 */
function toggleTaskData(taskID) {
    var id = '#'+taskID+'_data';
    $(id).slideToggle(400);
}