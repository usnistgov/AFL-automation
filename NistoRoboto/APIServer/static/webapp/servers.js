var numOfServers = 0; // counter for the number of Server objects made
var servers = []; // array for the Server objects

class Server {
    constructor(address) {
        this.address = address;
        this.key = 'S'+(++numOfServers);
        
        var addStatusBtnID = this.key+'_addStatusBtn';
        this.statusDiv = new Div(this.key,'status',addStatusBtnID);
        var addControlsBtnID = this.key+'_addControlsBtn';
        this.controlsDiv = new Div(this.key,'controls',addControlsBtnID);
        var addQueueBtnID = this.key+'_addQueueBtn';
        this.queueDiv = new Div(this.key,'queue',addQueueBtnID);
        var addQuickbarBtn = this.key+'_addQuickbarBtn';
        this.quickbarDiv = new Div(this.key,'quickbar',addQueueBtnID);

        var name;
        var link = this.address + 'get_info';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            async: false,
            success:function(result) {
                var r = JSON.parse(result);
                name = r["driver"];
            }
        });
        this.name = name;

        this.statusbarIDs = [this.key+'_sb_state', this.key+'_sb_time', ];
        $('#status-bar').append(this.name + ': <span id="'+this.statusbarIDs[0]+'"></span>, <span id="'+this.statusbarIDs[1]+'"></span> | ');
        
        servers.push(this);
        console.log(servers);
    }

    /**
     * Updates all shown info about the server
     */
    update() {
        var key = this.key;
        var state = '#'+this.statusbarIDs[0];
        var time = '#'+this.statusbarIDs[1];

        this.getQueueState(function(result) {
            $(state).text(result);
            var statusDiv = getDiv(key, 'status');
            var controlsDiv = getDiv(key, 'controls');
            var queueDiv = getDiv(key, 'queue');
            var quickbarDiv = getDiv(key, 'quickbar');
            statusDiv.update(result);
            queueDiv.update(result);
            controlsDiv.update(result);
            quickbarDiv.update(result);
        });

        this.getServerTime(function(result) {
            $(time).text(result);
        })
    }

    /**
     * Runs a GET ajax call for the server's queue which runs success_func on success
     * @param {Function} success_func 
     */
    getQueue(success_func) {
        var link = this.address + 'get_queue';
        $.ajax({
            type:"GET",
            dataType:"json",
            url:link,
            success:success_func
        });
    }

    /**
     * Runs a GET ajax call for the server's queued commands which runs success_func on success
     * @param {Function} success_func 
     */
    getQueuedCommands(success_func) {
        var link = this.address + 'get_queued_commands';
        $.ajax({
            type:"GET",
            dataType:"json",
            url:link,
            success:success_func
        });
    }

    /**
     * Runs a GET ajax call for the server's unqueued commands which runs success_func on success
     * @param {Function} success_func 
     */
    getUnqueuedCommands(success_func) {
        var link = this.address + 'get_unqueued_commands';
        $.ajax({
            type:"GET",
            dataType:"json",
            url:link,
            success:success_func
        });
    }

    /**
     * Runs a GET ajax call for the server's quickbar output which runs success_func on success
     * @param {Function} success_func 
     */
    getQuickbar(success_func) {
        var link = this.address + 'get_quickbar';
        $.ajax({
            type:"GET",
            dataType:"json",
            url:link,
            success:success_func
        });
    }

    /**
     * Runs a GET ajax call for the server's queue state which runs success_func on success
     * @param {Function} success_func 
     */
    getQueueState(success_func) {
        var link = this.address + 'queue_state';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            success:success_func
        });
    }

    /**
     * Runs a GET ajax call for the server's info which runs success_func on success
     * @param {Function} success_func 
     */
    getInfo(success_func) {
        var link = this.address + 'get_info';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            success:success_func
        });
    }

    /**
     * Runs a GET ajax call for the server's driver status which runs success_func on success
     * @param {Function} success_func 
     */
    getDriverStatus(success_func) {
        var link = this.address + 'driver_status';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            success:success_func
        });
    }

    /**
     * Runs a GET ajax call for the server's time which runs success_func on success
     * @param {Function} success_func 
     */
    getServerTime(success_func) {
        var link = this.address + 'get_server_time';
        $.ajax({
            type:"GET",
            dataType:"text",
            url:link,
            success:success_func
        });
    }

    /**
     * Runs a POST ajax call to halt
     */
    halt() {
        var link = this.address + 'halt';
        $.ajax({
            type:"POST",
            dataType:"text",
            url:link,
            success: function(result) {
                console.log(result);
            }
        });
    }

    /**
     * Runs a POST ajax call to clear the server's queue
     */
    clearQueue() {
        var link = this.address + 'clear_queue';
        $.ajax({
            type:"POST",
            dataType:"text",
            url:link,
            success: function(result) {
                console.log(result);
            }
        });
    }

    /**
     * Runs a POST ajax call to clear the server's queue
     */
    executeQuickbarTask(task) { 

      var address = this.address + 'enqueue';
      var params = $(`.${task.replaceAll(' ','_').toLowerCase()}_params`).toArray()

      var python_param, python_type,value;

      // first need to build json task data that we'll
      // send to the APIServer
      var task_dict = {'task_name':task};
      var value;
      for(let key in params){
        python_param = params[key].getAttribute('python_param')
        python_type = params[key].getAttribute('python_type')
        if(python_type=='float'){
          value = parseFloat(getInputValue(params[key]))
        } else if (python_type=='int'){
          value = parseInt(getInputValue(params[key]))
        } else if (python_type=='text'){
          value = getInputValue(params[key])
        } else if (python_type=='bool'){
          value = params[key].checked
        } else {
          throw `Not set up to parse this python_type: ${python_type}`
        }
        task_dict[python_param] = value
      }
      console.log("Quickbar Task Dict:",task_dict)

      // Make sure we're logged in
      // XXX Need to check for staleness of this token...
      if(!localStorage["token"]){
        api_login(this.address,"domo_arigato")
      }

      // Send request to APIServer
      $.ajax({
          type:"POST",
          contentType:"application/json",
          url:address,
          data: JSON.stringify(task_dict),
          beforeSend: function(request){
              request.withCredentials = true;
              request.setRequestHeader("Authorization", "Bearer " + localStorage.getItem('token'));
          },
          success: function(result) {
              console.log(result);
          }
      });
    }

    /**
     * Runs a POST ajax call to clear the server's history
     */
    clearHistory() {
        var link = this.address + 'clear_history';
        $.ajax({
            type:"POST",
            dataType:"text",
            url:link,
            success: function(result) {
                console.log(result);
            }
        });
    }

    /**
     * Runs a POST ajax call to pause or unpause the server's queue
     */
    pause() {
        var link = this.address + 'pause';
    
        this.getQueueState(function(result) {
            console.log(result);
            if(result == 'Paused') {
                $.ajax({
                    type:"POST",
                    url:link,
                    data: JSON.stringify({'state':false}),
                    success: function(result) {
                        console.log(result);
                    },
                    contentType: "application/json",
                    dataType: "json"
                });
            } else {
                $.ajax({
                    type:"POST",
                    url:link,
                    data: JSON.stringify({'state':true}),
                    success: function(result) {
                        console.log(result);
                    },
                    contentType: "application/json",
                    dataType: "json"
                });
            }
        });
    }
}

/**
 *Helper function for extracting values from 
 *input text fields
 */

function getInputValue(input){
  var value;
  if (input.value) {
    value = input.value
  } else {
    value = input.placeholder
  }
  return value
}

/**
 * Returns true if the url is a valid server and false if not
 * @param {String} url 
 * @returns {Boolean} isValid
 */
function isValidURL(url) {
    var link = url + 'get_queue'; // TODO change to something else
    var isValid = false;
    
    $.ajax({
        type:"GET",
        dataType:"json",
        url:link,
        async: false,
        success:function(result) {
            isValid = true;
        },
        error:function() {
            isValid = false;
        }
    }); 
    
    return isValid;
}

/**
 * Returns the server with the key attribute of the Server object
 * @param {String} key 
 * @returns {Server object}
 */
function getServer(key) {
    for(var i=0; i<servers.length; i++) {
        if(servers[i].key == key) {
            return servers[i];
        }
    }
    console.log('Server not found');
}

/**
 * Adds a server from the info recived from the popup
 * @param {Popup object} popup 
 */
function addServer(popup) {
    var route = document.getElementById(popup.inputs[0].id).value; // the address of the server to add
    if(route[route.length-1] != '/') {
        route = route + '/';
    }

    var isValid = isValidURL(route);
    if(isValid) {
        storeServerRoute(route);
        let server = new Server(route); // a new Server object created from the route

        addServerToMenu(server); // adds the menu items related to the server to the menu
        addQuickbarDiv(server.key);
        addStatusDiv(server.key);
        addControlsDiv(server.key);
        addQueueDiv(server.key);

        // // adds divs to the page if checked by user
        // var input;
        // for(var i=0; i<popup.inputs.length; i++) {
        //     input = document.getElementById(popup.inputs[i].id);
        //     if(input.type == 'checkbox') {
        //         if(input.checked == true) {
        //             if(input.id == 'status') {
        //                 addStatusDiv(server.key);
        //             } else if(input.id == 'controls') {
        //                 addControlsDiv(server.key);
        //             } else {
        //                 addQueueDiv(server.key);
        //             }
        //         }
        //     }
        // }

        closePopup();
    } else {
        alert('URL was not valid.');
    }
}

/**
 * Stores the server route in local storage (provided the route is not already stored)
 * @param {String} route 
 */
function storeServerRoute(route) {
    if(localStorage.getItem('routes') == null) {
        localStorage.setItem('routes',JSON.stringify([route]));
    } else {
        var storedRoutes = JSON.parse(localStorage.getItem('routes'));
        var found = false;

        for(let i=0; i<storedRoutes.length; i++) {
            if(storedRoutes[i] == route) {
                found = true;
            }
        }

        if(!found) {
            storedRoutes.push(route);
            localStorage.setItem('routes',JSON.stringify(storedRoutes));
        }
    }
    console.log('Stored Routes: ',localStorage.getItem('routes'));
}
