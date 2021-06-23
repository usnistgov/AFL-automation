class Popup {
    constructor(name) {
        this.name = name;

        var closeBtn = '<button onclick="closePopup()" style="float:right;">x</button>';
        var title = '<h3>'+this.name+'</h3>';
        this.html = closeBtn + title;

        this.inputs = [];
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
     * Adds the popup's html to the popup div in the html
     */
    addToHTML() {
        var content = this.html;
        if(this.inputs.length > 0) {
            content += '<br><button id="popupEnterBtn">Enter</button>';
        }
        $('#popup').append(content);
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
    $('#popup-background').css('visibility', 'hidden');
    $('#popup').empty();
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
 * Returns the task's meta data reformatted for jsTree
 * @param {JSON} data 
 */
 function formatData(data) {
    var keys = Object.keys(data);
    console.log(keys);
    var  id, parent, text;
    var items = [];
    for(let i in keys) {
        id = 'temp'+i;
        parent = '#'; // TODO change to allow for parents
        text = keys[i]+': '+data[keys[i]];

        var temp = '{"id": "'+id+'", "parent": "'+parent+'", "text": "'+text+'"}';
        items.push(temp);
    }

    var dataStr = '[';
    for (let i = 0; i  < items.length; i++) {
        if(i == items.length-1) {
            dataStr += items[i]+']';
        } else {
            dataStr += items[i]+',';
        }
    }

    return dataStr; 
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
        var title = 'Task: ' + result[x][y].task.task_name;
        let popup = new Popup(title);
        
        var task = JSON.stringify(result[x][y].task);
        popup.addText(task);
        popup.addToHTML();

        var data = JSON.parse(formatData(result[x][y].task));
        console.log(data);

        $('#popup').append('<div id="taskData1"></div>');
        $('#taskData1').jstree({
            'core': {
                'data': data
        }});
        // $('#taskData1').on("changed.jstree", function (e, data) {
        //     console.log(data.selected);
        // });

        displayPopup();
    });
}