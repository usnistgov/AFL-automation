class Popup {
    constructor(name,modal=true) {
        this.name = name;
        this.hasTaskData = false;
        this.modal=modal;

        // this.html = `<div id="dialog" class="modal fade" title="${this.name}" role="dialog">`;
      
        this.html = $(`<div class="modal" tabindex="-1" role="dialog">
          <div class="modal-dialog" role="document">
            <div class="modal-content">
              <div class="modal-header">
                <h5 class="modal-title">${this.name}</h5>
                <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                  <span aria-hidden="true">&times;</span>
                </button> 
              </div> 
              <div class="modal-body" id="popup-body"> 
              </div> 
              <div class="modal-footer" id="popup-footer">
              </div>
            </div>
          </div>
        </div>`)

        this.inputs = [];
        this.jsTrees = [];
        this.buttons = {};
    }

    /**
     * Adds a checkbox input to the popup's html
     * @param {String} id 
     * @param {String} name 
     * @param {String} label 
     */
    addCheckboxInput(id, name, label) {
        var html = '<input type="checkbox" id="'+id+'" name="'+name+'"><label for="'+name+'">'+label+'</label><br>';
        //this.html += html;
      
        this.html.find("#popup-body").append(html)
      
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
     * @param {String[]} datalist
     */
    addTextInput(id, name, label, placeholder, datalist = null) {
        var html = '<label for="'+name+'">'+label+': </label>';
        if(datalist != null) {
            html += '<input type="text" id="'+id+'" name="'+name+'" placeholder="'+placeholder+'" list="list-'+id+'">';
            html += '<datalist id="list-'+id+'">';
            for(let i=0; i<datalist.length; i++) {
                html += '<option value="'+datalist[i]+'">';
            }
            html += '</datalist><br>';
        } else {
            html += '<input type="text" id="'+id+'" name="'+name+'" placeholder="'+placeholder+'"><br>';
        }

        // this.html += html;
        this.html.find("#popup-body").append(html)
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
        // this.html += html;
        this.html.find("#popup-body").append(html)
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
        // this.html += html;
        this.html.find("#popup-body").append(html)
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
        text = JSON.stringify(data.task);

        // TODO solve the issue with generating 3+ levels in jsTree
        // html = '';
        // var add = buildListData(html, data);
        // html = '<div id="taskData"><ul>'+add+'</ul></div><p>'+text+'</p>';
        // console.log(html);

        keys = Object.keys(data.task);
        for(let i in keys) {
            root =  keys[i];
            child = data.task[keys[i]];
            html += '<li>'+root+'<ul><li>'+child+'</li></ul></li>';
        }
        html += '</ul></div><p>'+text+'</p>';

        // this.html += html;
        this.html.find("#popup-body").append(html)
        this.hasTaskData = true;
    }

    addBottomButton(name,callback) {
      var pname = this.name.replaceAll(' ','_');
      //var html = `<button id="${pname}_${name}_button" type="button" class="btn btn-primary">${name}</button>`
      var html = `<button id="${name}_button" type="button" class="btn btn-primary">${name}</button>`
      this.html.find("#popup-footer").append(html)
      this.buttons[name] = callback
    }

    /**
     * Adds the popup's html to the popup div in the html
     */
    addToHTML() {
        var content = this.html;

        $('body').append(content.html());
        $('.modal-dialog').draggable();
        // $('.modal-dialog').modal();
      

        for (let button_name in this.buttons) {
          // var button_id = '#' + this.name.replaceAll(' ','_') + '_' + button_name + '_button'
          var button_id = '#' + button_name + '_button'
          console.log(button_id)
          $(button_id).on('click',this.buttons[button_name])
        }

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
    $('#dialog').dialog('destroy').remove();
    
    if(queueEditorOpen == false) {
        $('#popup-background').css('visibility', 'hidden');
    }
}

/**
 * Creates and adds an add server popup
 */
function addServerPopup() {
    let popup = new Popup('Add a Server',modal=true);

    if(localStorage.getItem('routes') != null) {
        var storedRoutes = JSON.parse(localStorage.getItem('routes'));
        popup.addTextInput('userInput', 'route', 'Server Address', 'http://localhost:5051/', storedRoutes);
    } else {
        popup.addTextInput('userInput', 'route', 'Server Address', 'http://localhost:5051/');
    }

    popup.addCheckboxInput('status', 'status', 'Add Status');
    popup.addCheckboxInput('controls', 'controls', 'Add Controls');
    popup.addCheckboxInput('queue', 'queue', 'Add Queue');

    popup.addBottomButton("Enter",function() { console.log('Adding server');addServer(popup) })

    popup.addToHTML();
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
        let popup = new Popup(title, modal=false);
        var treeID = serverKey+'_taskJsTree';
        popup.addTaskData(treeID, result[x][y]);
        popup.addToHTML();
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
