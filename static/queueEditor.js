var queueTasks = []; // array for queued tasks
var removedTasks = []; // array for removed tasks
var numSelected, numSelectedShown, numShown, priorState;
var queueEditorOpen = false;

class Task {
    constructor(position, info) {
        this.ogPosition = position;
        this.position = position;
        this.info = info;
        this.selected = false;
        this.removed = false;
        this.shown = true;

        var name;
        if(this.info.task.hasOwnProperty('task_name')) {
            name = this.info.task.task_name;
        } else {
            name = JSON.stringify(this.info.task);
        }

        var uuid = this.info.uuid;
        var taskLabel = '<h4 onclick="select(\''+uuid+'\')" style="display:inline;">[<span class="taskPos">'+this.position+'</span>] '+name+'</h4>';
        var uuidLabel = '<p>(UUID: '+uuid+')</p>';
        var moveUpBtn = '<button onclick="moveTaskUp(\''+uuid+'\')">+</button>';
        var moveDownBtn = '<button onclick="moveTaskDown(\''+uuid+'\')">-</button>';
        var viewDataBtn = '<button onclick="displayTaskData(\''+uuid+'\')">&#x1F6C8;</button>';
        this.html = '<div id="'+uuid+'"><span class="taskControls" style="float:right;">'+moveUpBtn+moveDownBtn+viewDataBtn+'</span>'+taskLabel+uuidLabel+'<hr></div>';
    }

    /**
     * Toggles the task's 'selected' boolean attribute
     */
    select() {
        var id = '#'+this.info.uuid;

        if(this.removed == false) {
            if(this.selected == false) {
                this.selected = true;
                $(id).css('background-color','green');
                $(id).css('color','white');
                numSelected++;
                numSelectedShown++;
            } else {
                this.selected = false;
                $(id).css('background-color','white');
                $(id).css('color','black');
                numSelected--;
                numSelectedShown--;
            }
            $('#numSelected').html(numSelected);
            $('#numSelectedShown').html(numSelectedShown);
        }
    }

    /**
     * Toogles if the task is in the queue or not
     */
    remove() {
        var div = '#'+this.info.uuid;
        var pos = this.position;

        if(this.removed) {
            queueTasks.push(removedTasks.splice(pos,1).pop()); // removes the task from removedTasks and moves it to queueTasks
            this.position = queueTasks.length-1;
            this.removed = false;

            $(div).find('.taskPos').html(this.position); // changes the task label position

            // adds buttons to move task up or down one position + to view task meta data
            var moveUpBtn = '<button onclick="moveTaskUp(\''+this.info.uuid+'\')">+</button>';
            var moveDownBtn = '<button onclick="moveTaskDown(\''+this.info.uuid+'\')">-</button>';
            var viewDataBtn = '<button onclick="displayTaskData(\''+this.info.uuid+'\')">&#x1F6C8;</button>';
            var content = moveUpBtn+moveDownBtn+viewDataBtn;
            $(div).find('.taskControls').html(content);

            // changes the look of the task div
            $(div).css('background-color','white');
            $(div).css('color','black');

            // moves task div to bottom of queue
            var lastTask = '#'+queueTasks[queueTasks.length-2].info.uuid;
            $(div).insertAfter(lastTask);
        } else {
            this.select();
            removedTasks.push(queueTasks.splice(pos,1).pop()); // removes the task from queueTasks and moves it to removedTasks
            this.position = removedTasks.length-1;
            this.removed = true;

            $(div).find('.taskPos').html('-'); // changes the task label position to - to reflect it's removed
            
            // moves task div to bottom of queue
            var lastTask = '#'+queueTasks[queueTasks.length-1].info.uuid;
            $(div).insertAfter(lastTask);
            
            // adds button to task div to re-add task + removes move task up and move task down buttons
            var restoreBtn = '<button onclick="addTaskBack(\''+this.info.uuid+'\')">Re-Add Task</button>';
            var viewDataBtn = '<button onclick="displayTaskData(\''+this.info.uuid+'\')">&#x1F6C8;</button>';
            var content = restoreBtn+viewDataBtn;
            $(div).find('.taskControls').html(content);

            // changes the look of the task div
            $(div).css('background-color','black');
            $(div).css('color','white');

            // repostitions/corrects the positions of lower tasks
            while(pos<queueTasks.length) {
                queueTasks[pos].setPosition(pos);
                pos++;
            }
        }  
    }

    /**
     * Sets the task's position to the given position
     * @param {Integer} pos 
     */
    setPosition(pos) {
        if(this.position != pos) {
            this.position = pos; // sets the new task position
        
            var div = '#'+this.info.uuid;
            $(div).find('.taskPos').html(pos); // changes the task label to display the new position
        }
    }

    /**
     * Moves the tasks to a given position
     * @param {Integer} newPosition 
     */
    movePosition(newPosition) {
        var task = queueTasks.splice(this.position,1);
        var temp = queueTasks.splice(newPosition);

        queueTasks.push(task.pop());
        queueTasks = queueTasks.concat(temp);

        for(let i in queueTasks) {
            queueTasks[i].setPosition(i);
        }

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

/**
 * Sets up and opens the queue editor
 * @param {String} serverKey 
 */
function editQueue(serverKey) {
    var server = getServer(serverKey);
    api_login(server.address); // logs into api server

    numSelected = 0;
    numSelectedShown = 0;

    // pause the server
    server.getQueueState(function(result){
        priorState = result;
        if(result != 'Paused') {
            server.pause();
        }
    });

    // setup the queue editor w/ the server key
    server.getQueue(function(result) {
        for(let i in result[2]) {
            var tempTask = new Task(i, result[2][i]);
            queueTasks.push(tempTask);
        }

        var selectedInfo = '<span id="numSelected">0</span> Selected | <span id="numSelectedShown">0</span> Shown';
        var unselectAllBtn = '<button onclick="unselectAll()">Unselect</button>';
        var tasksShownInfo = '<span id="numShown">0</span> Task(s) Shown';
        var selectShownBtn = '<button onClick="selectShown()">Select Shown</button>';
        var unselectShownBtn = '<button onClick="unselectShown()">Unselect Shown</button>';

        var moveSelectedBtn = '<label for="newTaskPos">Move to Position: </label><input type="number" id="newTaskPos" name="newTaskPos" min="0"><button onclick="moveSelected(\'m\')">Enter</button>';
        var moveSelectedTopBtn = '<button onclick="moveSelected(\'t\')">Move to Top</button>';
        var moveSelectedBottomBtn = '<button onclick="moveSelected(\'b\')">Move to Bottom</button>';
        var removeSelectedBtn = '<button onclick="removeSelected()" style="background-color:red;color:white;">Remove</button>';
        var selectedControls = '<label>Selected Task(s): </label>'+selectedInfo+' | '+moveSelectedTopBtn+moveSelectedBottomBtn+removeSelectedBtn+unselectAllBtn+moveSelectedBtn;
        
        var closeBtn = '<button onclick="closeQueueEditor(\''+serverKey+'\')" style="float:right;">x</button>';
        var commitBtn = '<button onclick="commitQueueEdits(\''+serverKey+'\')">Commit Queue Edits</button>';
        var searchBar = '<label>Task Search: </label><input type="text" id="taskSearchBar" onkeyup="searchFilter()" placeholder="Search for tasks by name">';
        var editorControls = '<div id="queueEditorControls">'+closeBtn+commitBtn+' '+searchBar+'<br>'+tasksShownInfo+' '+selectShownBtn+unselectShownBtn+'<br>'+selectedControls+'</div><hr style="margin-top:100px;">';

        var tasks = '';
        numShown = 0;
        for(let i in queueTasks) {
            tasks += queueTasks[i].html;
            numShown++;
        }

        var content = editorControls + tasks;
        $('#queueEditor').html(content);
        $('#numShown').html(numShown);
    });

    // display the queue editor w/ the popup background
    $('#queueEditor').css('visibility', 'visible');
    $('#popup-background').css('visibility', 'visible');

    queueEditorOpen = true;
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
 * Unselects all selected tasks
 */
function unselectAll() {
    for(let i = 0; i<queueTasks.length; i++) {
        if(queueTasks[i].selected) {
            queueTasks[i].select();
        }
    }
}

/**
 * Selects all tasks shown in queue editor
 */
function selectShown() {
    for(let i = 0; i<queueTasks.length; i++) {
        if(queueTasks[i].shown) {
            if(!queueTasks[i].selected) {
                queueTasks[i].select();
            }
        }
    }
}

/**
 * Unselects all tasks shown in queue editor
 */
function unselectShown() {
    for(let i = 0; i<queueTasks.length; i++) {
        if(queueTasks[i].shown) {
            if(queueTasks[i].selected) {
                queueTasks[i].select();
            }
        }
    }
}

/**
 * Moves selected tasks to the top, the bottom, or to a specified position in the queue editor
 * @param {String} place 
 */
function moveSelected(place) {
    var selected = [];
    for(let i in queueTasks) {
        if(queueTasks[i].selected) {
            selected.push(queueTasks[i]);
        }
    }
    
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
                selected[i].movePosition(pos);
                pos++;
            }
        } else {
            alert('Error: cannot make this edit (more tasks than spaces available at that position in the queue)');
        }
    }
}

/**
 * Removes the selected tasks from the queue in the editor
 */
function removeSelected() {
    var selected = [];
    for(let i in queueTasks) {
        if(queueTasks[i].selected) {
            selected.push(queueTasks[i]);
        }
    }
    for(let i=0; i<selected.length; i++) {
        selected[i].remove();
    }
}

/**
 * Adds a removed task back to the queue
 * @param {String} taskID 
 */
function addTaskBack(taskID) {
    for(let i=0; i<removedTasks.length; i++) {
        if(removedTasks[i].info.uuid == taskID) {
            removedTasks[i].remove();
        }
    }
}

/**
 * Commits the edits made in the queue editor
 * @param {String} serverKey 
 */
function commitQueueEdits(serverKey) {
    var server = getServer(serverKey);
    
    if(removedTasks.length != 0) {
        var removed = [];
        let popup = new Popup('Removing Task(s) Comfirmation');

        for(let i=0; i<removedTasks.length; i++) {
            removed.push(removedTasks[i].info);
            var treeID = removedTasks[i].info.uuid+'_jsTree';
            popup.addTaskData(treeID,removedTasks[i].info);
        }
        console.log(removed);

        popup.addCheckboxInput('procceed','procceed','Yes, I want to remove the task(s) listed');
        popup.addToHTML();
        $('#popupEnterBtn').click(function() {
            var input = document.getElementById(popup.inputs[0].id);
            if(input.checked) {
                var link = server.address + 'remove_items';
                $.ajax({
                    url: link,
                    type: 'POST',
                    data: JSON.stringify(removed),
                    contentType: 'application/json',
                    beforeSend: function(request){
                        request.withCredentials = true;
                        request.setRequestHeader("Authorization", "Bearer " + localStorage.getItem('token'));
                    },
                    error : function(err) {
                        console.log('Enqueue Error!',err);
                        alert('Failed to remove items.');
                    },
                    success: function(result) {
                        console.log(result);
                        console.log('Removed items');
                        reorderQueue(serverKey);
                    }
                });
            } else {
                console.log('Did not confirm');
            }
            closePopup();
        });
        displayPopup();
    } else {
        reorderQueue(serverKey);
    }
}

/**
 * Reorders the server's queue to be identical to the queue editor's queue
 * @param {String} serverKey 
 */
function reorderQueue(serverKey) {
    var queue = [];
    for(let i=0; i<queueTasks.length; i++) {
        queue.push(queueTasks[i].info);
    }
    console.log(queue);
    var data = {'prior_state':priorState, 'queue':queue};

    var server = getServer(serverKey);
    var link = server.address + 'reorder_queue';
    $.ajax({
        url: link,
        type: 'POST',
        data: JSON.stringify(data),
        contentType: 'application/json',
        beforeSend: function(request){
            request.withCredentials = true;
            request.setRequestHeader("Authorization", "Bearer " + localStorage.getItem('token'));
        },
        error : function(err) {
            console.log('Enqueue Error!',err);
            alert('Failed to commit queue edits.');
        },
        success: function(result) {
            console.log(result);
            closeQueueEditor(serverKey); // closes the queue editor
        }
    });
}

/**
 * Closes the queue editor
 * @param {String} serverKey 
 */
function closeQueueEditor(serverKey) {
    queueTasks = []; // clears all tasks from queueTasks
    removedTasks = []; // clears all tasks from removedTasks

    // hide the queue editor w/ the popup background
    $('#queueEditor').css('visibility', 'hidden');
    $('#popup-background').css('visibility', 'hidden');
    $('#queueEditor').empty();

    var server = getServer(serverKey);
    server.getQueueState(function(result){
        if(priorState != result) {
            server.pause();
        }
    });

    queueEditorOpen = false;
}

/**
 * Filters the tasks shown in the queue editor based on the search bar input
 */
function searchFilter() {
    var input = $('#taskSearchBar').val().toUpperCase();
    var count = numSelected;
    var count2 = queueTasks.length;

    for(let i = 0; i<queueTasks.length; i++) {
        var taskID = '#'+queueTasks[i].info.uuid;
        if(queueTasks[i].info.task.task_name.toUpperCase().indexOf(input) > -1) {
            $(taskID).css('display','');
        } else {
            $(taskID).css('display','none');
            queueTasks[i].shown = false;

            --count2;
            if(queueTasks[i].selected) {
                --count;
            }
        }
    }

    numShown = count2;
    $('#numShown').html(numShown);
    numSelectedShown = count;
    $('#numSelectedShown').html(numSelectedShown);
}

/**
 * Displays the task's meta data
 * @param {String} taskID 
 */
function displayTaskData(taskID) {
    var popup, title, treeID;

    for(let i=0; i<queueTasks.length; i++) {
        if(queueTasks[i].info.uuid == taskID) {
            if(queueTasks[i].info.task.hasOwnProperty('task_name')) {
                title = 'Task: ' + queueTasks[i].info.task.task_name;
            } else {
                title = 'Task Meta Data';
            }
            popup = new Popup(title);

            treeID = taskID+'_jsTree';
            popup.addTaskData(treeID, queueTasks[i].info);
        }
    }
    for(let i=0; i<removedTasks.length; i++) {
        if(removedTasks[i].info.uuid == taskID) {
            if(queueTasks[i].info.task.hasOwnProperty('task_name')) {
                title = 'Task: ' + queueTasks[i].info.task.task_name;
            } else {
                title = 'Task Meta Data';
            }
            popup = new Popup(title);

            treeID = taskID+'_jsTree';
            popup.addTaskData(treeID, removedTasks[i].info);
        }
    }

    popup.addToHTML();
    displayPopup();
}

/**
 * Moves the task up one position in the queue editor
 * @param {String} taskID 
 */
function moveTaskUp(taskID) {
    var currPos, newPos;
    for(let i=0; i<queueTasks.length; i++) {
        if(queueTasks[i].info.uuid == taskID) {
            currPos = queueTasks[i].position; // gets task's current position
        }
    }

    if(currPos == 0) { // in case task is already at top of queue
        alert('Task is already at top of queue.');
    } else {
        newPos = currPos-1;
        queueTasks[currPos].movePosition(newPos); // moves task to up a position from current position
    }
}

/**
 * Moves the task down one position in the queue editor
 * @param {String} taskID 
 */
function moveTaskDown(taskID) {
    var currPos, newPos, bottom;
    bottom = queueTasks.length-1;

    for(let i=0; i<queueTasks.length; i++) {
        if(queueTasks[i].info.uuid == taskID) {
            currPos = queueTasks[i].position; // gets task's current position
        }
    }

    if(currPos == bottom) { // in case task is already at bottom of queue
        alert('Task is already at bottom of queue.');
    } else {
        newPos = currPos++;
        queueTasks[currPos].movePosition(newPos); // moves the task below up a position
    }
}

/**
 * Logs into the api server given the server's url
 * @param {String} url 
 */
function api_login(url){
    var link = url+'login';
    $.ajax({
        url:link,
        type: 'POST',
        data:'{"username":"HTML","password":"domo_arigato"}',
        contentType:'application/json',
        error : function(err) {
            console.log('Login Error!',err)
        },
        success : function(data) {
            console.log('Login Success!',data)
            localStorage.setItem('token',data.token)
        }
    });
 }