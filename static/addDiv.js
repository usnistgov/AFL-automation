class Div {
    constructor(serverKey, type, addBtnID) {
        this.serverKey = serverKey;
        this.type = type;
        this.addBtnID = addBtnID;
        this.id = serverKey + '_' + type;
        this.div = '<div id="'+this.id+'" class="container" serverKey="'+this.serverKey+'" divType="'+this.type+'"></div>';
    }

    /**
     * Adds the div to the html and fills it in accordance to the div type
     */
    add() {
        $("#containers").append(this.div);
        this.#addDivControls();
        this.#addHeader();

        var contentDiv;
        var content;

        if(this.type == 'status') {
            // TODO make content specific for div type
            content = '<p>the content</p>';
            contentDiv = '<div class="content">'+content+'</div>';
        }
        if(this.type == 'controls') {
            // TODO make content specific for div type
            content = '<p>the content</p>';
            contentDiv = '<div class="content">'+content+'</div>';
        }
        if(this.type == 'queue') {
            // TODO make content specific for div type
            content = '<p>the content</p>';
            contentDiv = '<div class="content">'+content+'</div>';
        }

        this.#addToDiv(contentDiv);
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

}

/**
 * Creates and adds a status div for the corresponding server
 * @param {String} btnID 
 */
function addStatusDiv(btnID) {
    id = '#'+btnID;
    var serverKey = $(id).attr('serverKey');
    // console.log(serverKey); // prints the serverKey to the console
    
    var div = new Div(serverKey, 'status', btnID);
    div.add();
    // console.log(div); // prints the div object to the console

    disableBtn($(id));
}

/**
 * Creates and adds a controls div for the corresponding server
 * @param {String} btnID 
 */
function addControlsDiv(btnID) {
    id = '#'+btnID;
    var serverKey = $(id).attr('serverKey');
    // console.log(serverKey); // prints the serverKey to the console
    
    var div = new Div(serverKey, 'controls', btnID);
    div.add();
    // console.log(div); // prints the div object to the console
    
    disableBtn($(id));
}

/**
 * Creates and adds a queue div for the corresponding server
 * @param {String} btnID 
 */
function addQueueDiv(btnID) {
    id = '#'+btnID;
    var serverKey = $(id).attr('serverKey');
    // console.log(serverKey); // prints the serverKey to the console
    
    var div = new Div(serverKey, 'queue', btnID);
    div.add();
    // console.log(div); // prints the div object to the console
    
    disableBtn($(id));
}