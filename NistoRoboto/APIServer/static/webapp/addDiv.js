class Div {
    constructor(serverKey, type, addBtnID) {
        this.serverKey = serverKey;
        this.type = type;
        this.addBtnID = addBtnID;
        this.id = serverKey + '_' + type;
        this.div = '<div id="'+this.id+'" class="container" serverKey="'+this.serverKey+'" divType="'+this.type+'"></div>';
        this.onScreen = false;
    }

    /**
     * Sets the onScreen attribute to the boolean passed
     * @param {Boolean} bool 
     */
    setOnScreen(bool) {
        this.onScreen = bool;
    }

    /**
     * Adds the div to the html and fills it in accordance to the div type
     */
    display() {
        $("#column1").append(this.div);
        this.#addDivControls();
        this.#addHeader();

        var contentDiv;

        if(this.type == 'status') {
            contentDiv = '<div class="content">'+this.#statusContent()+'</div>';
        } else if(this.type == 'controls') {
            contentDiv = '<div class="content">'+this.#controlsContent()+'</div>';
        } else if(this.type == 'queue') {
            contentDiv = '<div class="content">'+this.#queueContent()+'</div>';
        } else if(this.type == 'quickbar') {
            contentDiv = '<div class="content">'+this.#quickbarContent()+'</div>';
        } else {
          throw "Div type not recognized!"
        }

        this.#addToDiv(contentDiv);
        this.setOnScreen(true);
    }

    /**
     * Updates the div's color and content if the div is on screen
     * @param {String} status 
     */
    update(status) {
        if(this.onScreen) {
            this.updateDivColor(status);
            this.updateDivContent();
        }
    }

    /**
     * Updates the background color of the div to correspond to the server's status
     * @param {String} status 
     */
    updateDivColor(status) {
        var id = '#' + this.id;
        if(status == 'Paused') {
            $(id).css('background-color', '#FFBF00');
        } else if(status == 'Debug') {
            // Q - what should be the debug color?
            $(id).css('background-color', 'darkcyan');
        } else if(status == 'Active') {
            $(id).css('background-color', 'green');
        } else {
            $(id).css('background-color', 'white');
        }
    }

    /**
     * Updates the content of the div with server info
     */
    updateDivContent() {
        var server = getServer(this.serverKey);

        if(this.type == 'status') {
            this.#updateStatusContent(server);
        }

        if(this.type == 'queue') {
            this.#updateQueueContent(server);
        }

        if(this.type == 'controls') {
            this.#updateControlsContent();
        }
    }

    /**
     * Adds the content to the div in the html
     * @param {String} content 
     */
    #addToDiv(content) {
        var id = '#' + this.id;
        $(id).append(content);
    }
    
    /**
     * Adds the div controls to the div in the html
     */
    #addDivControls() {
        var colExp = '<button onclick="collapseDiv('+this.id+')" class="col_exp_btn">Collapse</button>';
        var closeBtn = '<button onclick="closeDiv('+this.id+')" class="closebtn">x</button>';
        var divControls = '<span style="float:right;">'+colExp+closeBtn+'</span>';

        this.#addToDiv(divControls);
    }

    /**
     * Adds the div header to the div in the html
     */
    #addHeader() {
        var server = getServer(this.serverKey);
        var headerContent = '<h3>'+server.name+' - '+this.type+'</h3>';
        var headerDiv = '<div class="header">'+headerContent+'</div>';

        this.#addToDiv(headerDiv);

        // TODO add the collapse div function on double click of the header
        var header = '#'+this.id+'.header';
        $(header).dblclick(function() {
            console.log('event');
        });
    }

    /**
     * Creates and returns the status div content
     * @returns String of html content for status div
     */
    #statusContent() {
        var driverID = this.serverKey + '_driver';
        var stateID = this.serverKey + '_state';
        var experimentID = this.serverKey + '_experiment';
        var numCompletedID = this.serverKey + '_numCompleted';
        var numQueuedID = this.serverKey + '_numQueued';
        var dateTimeID = this.serverKey + '_dateTime';
        var topContent = '<p>Driver: <span id="'+driverID+'">[driver name]</span> | Queue State: <span id="'+stateID+'">[state]</span> | Experiment: <span id="'+experimentID+'">[experiment]</span> | Completed: <span id="'+numCompletedID+'">[#]</span> | Queue: <span id="'+numQueuedID+'">[#]</span> | Time: <span id="'+dateTimeID+'">[time] [date]</span></p>';

        var driverStatusID = this.serverKey + '_driverStatus';
        var bottomContent = '<p><span id="'+driverStatusID+'"></span></p>';
        var content = topContent + '<hr>' + bottomContent;

        return content;
    }

    /**
     * Updates the content of a status div
     * @param {Server} server 
     */
    #updateStatusContent(server) {
        var driverID = '#' + this.serverKey + '_driver';
        var stateID = '#' + this.serverKey + '_state';
        var experimentID = '#' + this.serverKey + '_experiment';
        var numCompletedID = '#' + this.serverKey + '_numCompleted';
        var numQueuedID = '#' + this.serverKey + '_numQueued';
        var driverStatusID = '#' + this.serverKey + '_driverStatus';
        var dateTimeID = '#' + this.serverKey + '_dateTime';

        server.getInfo(function(result) {
            var r = JSON.parse(result);

            $(driverID).text(r["driver"]);
            $(stateID).text(r["queue_state"]);
            $(experimentID).text(r["experiment"]);

            var completed = r.queue[0].length;
            $(numCompletedID).text(completed);

            var queued = r.queue[2].length + r.queue[1].length;
            $(numQueuedID).text(queued);
        });

        server.getDriverStatus(function(result) {
            var r = JSON.parse(result);
            var status = '';

            for(let i in r) {
                status += r[i] + ' | ';
            }
            
            $(driverStatusID).text(status);
        });

        server.getServerTime(function(result) {
            $(dateTimeID).text(result);
        })
    }

    /**
     * Creates and returns the controls div content
     * @returns String of html content for controls div
     */
    #controlsContent() {
        var haltBtn = '<button class="halt-btn" onclick="halt(\''+this.serverKey+'\')">HALT</button>';
        var clearQueueBtn = '<button onclick="clearQueue(\''+this.serverKey+'\')">Clear Queue</button>';
        var clearHistoryBtn = '<button onclick="clearHistory(\''+this.serverKey+'\')">Clear History</button>';
        var togglePauseBtn = '<button onclick="pause(\''+this.serverKey+'\')">Pause/Unpause</button>';
        var editQueueBtn = '<button onclick="editQueue(\''+this.serverKey+'\')">Edit Queue</button>';

        var additionalControlsID = this.serverKey+'_additionalControls';
        var additionalControls = '<ul id="'+additionalControlsID+'"></ul>';
        // TODO make additional controls appear as a dropdown when needed based on screen size

        var content = haltBtn + clearQueueBtn + clearHistoryBtn + togglePauseBtn + editQueueBtn + additionalControls;
        return content;
    }

    /**
     * Updates the content of a controls div
     */
    #updateControlsContent() {
        var additionalControlsID = '#'+this.serverKey+'_additionalControls';
        var queuedCommands = '#'+this.serverKey+'_queuedCommands';
        var unqueuedCommands = '#'+this.serverKey+'_unqueuedCommands';

        var fill = '<li style="display: none;">Additional Controls</li>'+$(queuedCommands).html()+$(unqueuedCommands).html();
        
        $(additionalControlsID).html(fill);
    }

    /**
     * Creates and returns the queue div content
     * @returns String of html content for queue div
     */
    #queueContent(){
        var completedID = this.serverKey + '_history';
        var completed = '<div class="queue_tasks"><ul id="'+completedID+'"></ul></div>';

        var uncompletedID = this.serverKey + '_queued';
        var uncompleted = '<div class="queue_tasks"><ul id="'+uncompletedID+'"></ul></div>';

        var currentID = this.serverKey + '_current';
        var current = '<span id="'+currentID+'"></span>';

        var content = '<ul><li>'+ completed +'</li><hr>'+current+'<hr><li>'+ uncompleted +'</li></ul>';
        return content;
    }

    /**
     * Creates and returns the quickbar div content
     * @returns String of html content for queue div
     */
    #quickbarContent(){
        var haltBtn = '<button class="halt-btn" onclick="halt(\''+this.serverKey+'\')">HALT</button>';
        var clearQueueBtn = '<button onclick="clearQueue(\''+this.serverKey+'\')">Clear Queue</button>';
        var clearHistoryBtn = '<button onclick="clearHistory(\''+this.serverKey+'\')">Clear History</button>';
        var togglePauseBtn = '<button onclick="pause(\''+this.serverKey+'\')">Pause/Unpause</button>';
        var editQueueBtn = '<button onclick="editQueue(\''+this.serverKey+'\')">Edit Queue</button>';

        var additionalControlsID = this.serverKey+'_quickbarContent';
        var additionalControls = '<ul id="'+additionalControlsID+'"></ul>';
        // TODO make additional controls appear as a dropdown when needed based on screen size

        var content = haltBtn + clearQueueBtn + clearHistoryBtn + togglePauseBtn + editQueueBtn + additionalControls;
        return content;
    }

    /**
     * Updates the content of a queue div
     * @param {Server} server 
     */
    #updateQueueContent(server) {
        var completedID = '#' + this.serverKey + '_history';
        var uncompletedID = '#' + this.serverKey + '_queued';
        var currentID = '#' + this.serverKey + '_current';
        var key = this.serverKey;

        server.getQueue(function(result) {
            $(completedID).empty();
            for(let i in result[0]) {
                var task = '<li onclick="addTaskPopup(\''+key+'\',0,'+i+')">'+result[0][i].task.task_name+'</li>';
                $(completedID).append(task);
            }

            $(currentID).empty();
            if(result[1].length > 0) {
                var currentTask = '<li onclick="addTaskPopup(\''+key+'\',1,0)" class="currentTask">'+result[1][0].task.task_name+'</li>';
                $(currentID).append(currentTask);
            }

            $(uncompletedID).empty();
            for(let i in result[2]) {
                var task = '<li onclick="addTaskPopup(\''+key+'\',2,'+i+')">'+result[2][i].task.task_name+'</li>';
                $(uncompletedID).append(task);
            }
        });
    }
}

/**
 * Halts the server given the server key
 * @param {String} serverKey 
 */
function halt(serverKey) {
    var server = getServer(serverKey);
    server.halt();
}

/**
 * Clear's the server's queue given the server key
 * @param {String} serverKey 
 */
function clearQueue(serverKey) {
    var server = getServer(serverKey);
    server.clearQueue();
}

/**
 * Clear's the server's history given the server key
 * @param {String} serverKey 
 */
function clearHistory(serverKey) {
    var server = getServer(serverKey);
    server.clearHistory();
}

/**
 * Pauses/Unpauses the server's queue given the server key
 * @param {String} serverKey 
 */
function pause(serverKey) {
    var server = getServer(serverKey);
    server.pause();
}

/**
 * Returns a particular div object given the server key and the div type 
 * @param {String} serverKey 
 * @param {String} divType 
 * @returns Div object
 */
function getDiv(serverKey, divType) {
    var server = getServer(serverKey);
    if(divType == 'status') {
        return server.statusDiv;
    } else if(divType == 'controls') {
        return server.controlsDiv;
    } else if(divType == 'queue') {
        return server.queueDiv;
    } else if(divType == 'quickbar') {
        return server.quickbarDiv;
    } else {
      throw "Div not found!"
    }
}

/**
 * Creates and adds a status div for the corresponding server
 * @param {String} key
 */
function addStatusDiv(key) {
    var server = getServer(key);
    server.statusDiv.display();

    var id = '#'+server.statusDiv.addBtnID;
    disableBtn($(id));
}

/**
 * Creates and adds a controls div for the corresponding server
 * @param {String} key
 */
function addControlsDiv(key) {
    var server = getServer(key);
    server.controlsDiv.display();

    var id = '#'+server.controlsDiv.addBtnID;
    disableBtn($(id));
}

/**
 * Creates and adds a queue div for the corresponding server
 * @param {String} key
 */
function addQueueDiv(key) {
    var server = getServer(key);
    server.queueDiv.display();

    var id = '#'+server.queueDiv.addBtnID;
    disableBtn($(id));
}

/**
 * Creates and adds a quickbar div for the corresponding server
 * @param {String} key
 */
function addQuickbarDiv(key) {
    var server = getServer(key);
    server.quickbarDiv.display();

    var id = '#'+server.quickbarDiv.addBtnID;
    disableBtn($(id));
}
