class Div {
    constructor(serverKey, type, addBtnID) {
        this.serverKey = serverKey;
        this.type = type;
        this.addBtnID = addBtnID;
        this.id = serverKey + '_' + type;
        this.div = '<div id="'+this.id+'" class="container" serverKey="'+this.serverKey+'" divType="'+this.type+'"></div>';
        this.onScreen = false;
    }

    setOnScreen(bool) {
        this.onScreen = bool;
    }

    /**
     * Adds the div to the html and fills it in accordance to the div type
     */
    add() {
        $("#containers").append(this.div);
        this.#addDivControls();
        this.#addHeader();

        var contentDiv;

        if(this.type == 'status') {
            contentDiv = '<div class="content">'+this.#statusContent()+'</div>';
        }
        if(this.type == 'controls') {
            contentDiv = '<div class="content">'+this.#controlsContent()+'</div>';
        }
        if(this.type == 'queue') {
            contentDiv = '<div class="content">'+this.#queueContent()+'</div>';
        }

        this.#addToDiv(contentDiv);
        this.setOnScreen(true);

        var server = getServer(this.serverKey);
        server.updateDivs();
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
            $(id).css('background-color', 'blue');
        } else if(status == 'Active') {
            $(id).css('background-color', 'green');
        } else {
            $(id).css('background-color', 'white');
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
        var colExp = '<button onclick="collapseDiv('+this.id+')">Collapse/Expand</button>';
        var closeButton = '<button onclick="closeDiv('+this.id+')" class="closebtn">x</button>';
        var divControls = '<span style="float:right;">'+colExp+closeButton+'</span>';

        this.#addToDiv(divControls);
    }

    /** NOT FINISHED
     * Adds the div header to the div in the html
     */
    #addHeader() {
        var headerContent = '<h3>'+this.serverKey+' - '+this.type+'</h3>'; // TODO (after finishing Server class) should be the server name
        var headerDiv = '<div class="header">'+headerContent+'</div>';

        this.#addToDiv(headerDiv);

        // TODO add the collapse div function on double click of the header
        var header = '#'+this.id+'.header';
        $(header).dblclick(function() {
            console.log('event');
        });
    }

    updateDivContent() {
        var server = getServer(this.serverKey);

        if(this.type == 'status') {
            
        }

        if(this.type == 'queue') {
            var completedID = '#' + this.serverKey + '_history';
            var currentID = '#' + this.serverKey + '_running';
            var upcomingID = '#' + this.serverKey + '_queued';

            server.getQueue(function(result) {
                // console.log(result);

                $(completedID).empty();
                for(let i in result[0]) {
                    // console.log(result[0][i]);
                    var task = '<li>'+result[0][i].task.task_name+'</li>';
                    $(completedID).append(task);
                }

                $(currentID).empty();
                for(let i in result[1]) {
                    // console.log(result[0][i]);
                    var task = '<li>'+result[1][i].task.task_name+'</li>';
                    $(currentID).append(task);
                }

                $(upcomingID).empty();
                for(let i in result[2]) {
                    // console.log(result[0][i]);
                    var task = '<li>'+result[2][i].task.task_name+'</li>';
                    $(upcomingID).append(task);
                }
            });
        }
    }

    /**
     * Creates and returns the status div content
     * @returns String of html content for status div
     */
    #statusContent() {
        // TODO fill in top content with ???
        var topContent = '<p>Driver: [driver name] | Queue State: [state] | Experiment: Development | Completed: # | Queue: # | Time: [date] [time]</p>';
        // TODO fill in bottom content with driver status
        var bottomContent = '<p>[Info from server] | [Info from server] | [Info from server]</p>';
        var content = topContent + '<hr>' + bottomContent;
        return content;
    }

    /**
     * Creates and returns the controls div content
     * @returns String of html content for controls div
     */
    #controlsContent() {
        var haltBtn = '<button class="halt-btn">HALT</button>';
        var clearQueueBtn = '<button>Clear Queue</button>';
        var clearHistoryBtn = '<button>Clear History</button>';
        var togglePauseBtn = '<button>Pause/Unpause</button>';

        queuedCommands = '#'+this.serverKey+'_queuedCommands';
        unqueuedCommands = '#'+this.serverKey+'_unqueuedCommands';
        var addtionalControls = '<ul><li style="display: none;">Additional Controls</li>'+$(queuedCommands).html()+$(unqueuedCommands).html()+'</ul>';

        var content = haltBtn + clearQueueBtn + clearHistoryBtn + togglePauseBtn + addtionalControls;
        return content;
    }

    /**
     * Creates and returns the queue div content
     * @returns String of html content for queue div
     */
    #queueContent(){
        var completedID = this.serverKey + '_history';
        var completed = '<h4>Completed</h4><ul id="'+completedID+'"></ul>';

        var currentID = this.serverKey + '_running';
        var current = '<h4>Current Task</h4><ul id="'+currentID+'"></ul>';
        
        var upcomingID = this.serverKey + '_queued';
        var upcoming = '<h4>Upcoming</h4><ul id="'+upcomingID+'"></ul>';

        var content = '<ul><li>'+ upcoming +'</li><li>'+ current +'</li><li>'+ completed +'</li></ul>';
        return content;
    }
}

function getDiv(serverKey, divType) {
    var server = getServer(serverKey);
    if(divType == 'status') {
        return server.statusDiv;
    }
    if(divType == 'controls') {
        return server.controlsDiv;
    }
    if(divType == 'queue') {
        return server.queueDiv;
    }
}

/**
 * Creates and adds a status div for the corresponding server
 * @param {String} key
 */
function addStatusDiv(key) {
    var server = getServer(key);
    server.statusDiv.add();

    var id = '#'+server.statusDiv.addBtnID;
    disableBtn($(id));
}

/**
 * Creates and adds a controls div for the corresponding server
 * @param {String} key
 */
function addControlsDiv(key) {
    var server = getServer(key);
    server.controlsDiv.add();

    var id = '#'+server.controlsDiv.addBtnID;
    disableBtn($(id));
}

/**
 * Creates and adds a queue div for the corresponding server
 * @param {String} key
 */
function addQueueDiv(key) {
    var server = getServer(key);
    server.queueDiv.add();

    var id = '#'+server.queueDiv.addBtnID;
    disableBtn($(id));
}