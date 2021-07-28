class Popup {
    constructor(name) {
        this.name = name;
        this.hasTaskData = false;

        var closeBtn = '<button onclick="closePopup()" style="float:right;">x</button>';
        var title = '<h3>'+this.name+'</h3>';
        this.html = closeBtn + title;

        this.inputs = [];
        this.jsTrees = [];
    }

    /**
     * Adds a checkbox input to the popup's html
     * @param {String} id 
     * @param {String} name 
     * @param {String} label 
     */
    addCheckboxInput(id, name, label) {
        var html = '<input type="checkbox" id="'+id+'" name="'+name+'"><label for="'+name+'">'+label+'</label><br>';
        this.html += html;
        this.inputs.push({
            id: id,
            type: 'checkbox',
            name: name
        });
    }

    /**
     * Adds a text input to the popup's html
     * @param {String} id 
     * @param {String} name 
     * @param {String} label 
     * @param {String} placeholder 
     */
    addTextInput(id, name, label, placeholder) {
        var html = '<label for="'+name+'">'+label+': </label><input type="text" id="'+id+'" name="'+name+'" placeholder="'+placeholder+'"><br>';
        this.html += html;
        this.inputs.push({
            id: id,
            type: 'text',
            name: name
        });
    }

    /**
     * Adds a number input to the popup's html
     * @param {String} id 
     * @param {String} name 
     * @param {String} label 
     * @param {number} min 
     * @param {number} max 
     */
    addNumberInput(id, name, label, min, max) {
        var html = '<label for="'+name+'">'+label+': </label><input type="number" id="'+id+'" name="'+name+'" min="'+min+'" max="'+max+'"><br>';
        this.html += html;
        this.inputs.push({
            id: id,
            type: 'number',
            name: name
        });
    }

    /**
     * Adds text to the popup's html
     * @param {String} text 
     */
    addText(text) {
        var html = '<p>'+text+'</p>';
        this.html += html;
    }

    /**
     * Adds task meta data as jsTree and plain text to popup's html
     * @param {String} id
     * @param {JSON} data 
     */
    addTaskData(id, data) {
        this.jsTrees.push(id);
        var keys, root, child, html, text;
        html = '<div id="'+id+'" class="jsTree"><ul>';
        text = JSON.stringify(data);

        // TODO solve the issue with generating 3+ levels in jsTree
        // html = '';
        // var add = buildListData(html, data);
        // html = '<div id="taskData"><ul>'+add+'</ul></div><p>'+text+'</p>';
        // console.log(html);

        keys = Object.keys(data);
        for(let i in keys) {
            root =  keys[i];
            child = data[keys[i]];
            html += '<li>'+root+'<ul><li>'+child+'</li></ul></li>';
        }
        html += '</ul></div><p>'+text+'</p>';

        this.html += html;
        this.hasTaskData = true;
    }

    /**
     * Adds the popup's html to the popup div in the html
     */
    addToHTML() {
        var content = this.html;
        if(this.inputs.length > 0) {
            content += '<br><button id="popupEnterBtn">Enter</button>';
        }
        $('#popup').append(content);

        if(this.hasTaskData){
            for(let i = 0; i<this.jsTrees.length; i++) {
                var treeID = '#'+this.jsTrees[i];
                $(treeID).on('ready.jstree', function() {
                    $(treeID).jstree('open_all');
                });
                $(treeID).jstree(); // creates the JsTree
            }
        }
    }
}

/**
 * Displays the popup on screen
 */
function displayPopup() {
    $('#popup').css('visibility', 'visible');
    $('#popup-background').css('visibility', 'visible');
}

/**
 * Hides the popup from view and empties the popup div
 */
function closePopup() {
    $('#popup').css('visibility', 'hidden');
    $('#popup').empty();
    
    if(queueEditorOpen == false) {
        $('#popup-background').css('visibility', 'hidden');
    }
}

/**
 * Creates and adds an add server popup
 */
function addServerPopup() {
    let popup = new Popup('Add a Server');

    popup.addTextInput('userInput', 'route', 'Server Address', 'Server Address');
    popup.addCheckboxInput('status', 'status', 'Add Status');
    popup.addCheckboxInput('controls', 'controls', 'Add Controls');
    popup.addCheckboxInput('queue', 'queue', 'Add Queue');

    popup.addToHTML();

    $('#popupEnterBtn').click(function() {
        addServer(popup);
    });

    displayPopup();
}

/**
 * Displays all information about a task in a popup
 * @param {String} serverKey 
 * @param {Integer} x 
 * @param {Integer} y 
 */
function addTaskPopup(serverKey, x, y) {
    var server = getServer(serverKey);

    server.getQueue(function(result) {
        var title;
        if(result[x][y].task.hasOwnProperty('task_name')) {
            title = 'Task: ' + result[x][y].task.task_name;
        } else {
            title = 'Task Meta Data';
        }
        let popup = new Popup(title);
        var treeID = serverKey+'_taskJsTree';
        popup.addTaskData(treeID, result[x][y].task);
        popup.addToHTML();
        displayPopup();
    });
}

/**
 * (inprogress) Returns JSON data as HTML list
 * @param {String} html 
 * @param {JSON} input 
 * @returns 
 */
function buildListData(html,input) {
    var keys = Object.keys(input);

    for(let i in keys) {
        html += '<li>'+keys[i]+'</li>';

        if(typeof(input[keys[i]]) == 'object') {
            html += '<ul>';
            var temp2 = '';
            html += buildListData(temp2, input[keys[i]]);
            html += '</ul>';
        } else {
            html += '<ul><li>'+input[keys[i]]+'</li></ul>';
        }
    }
    
    console.log(html);
    return html;
}