function update(){
    $.get( "get_queue", function( result ) {
        task_history = result[0];
    
        var queue_num = 0;
        ul_history = $("<ul class=element>");
        for (var i=0, l=task_history.length; i<l; ++i) {
            var meta_str = "meta" + queue_num;
            ul_history.append(
                                "<li class='element history' data-div=" + meta_str + ">" + 
                                i + ") " + 
                                JSON.stringify(task_history[i]['task']) + 
                                "</li>" +
                                "<div class='hidden meta' id=" + meta_str + ">"+
                                JSON.stringify(task_history[i]['meta']) + 
                                "</div>" 
            );
            if ($('#' + meta_str).length) {
                if ($('#' + meta_str).is(':visible')) {
                    ul_history.children().last().last().show();
                } else {
                    ul_history.children().last().last().hide();
                }
            } else {
                ul_history.children().last().last().hide();
            }
            queue_num += 1;
        }
            
        task_running = result[1];
        ul_running = $("<ul class=element>");
        for (var i=0, l=task_running.length; i<l; ++i) {
            var meta_str = "meta" + queue_num;
            ul_running.append(
                                "<li class='element running' data-div=" + meta_str + ">" + 
                                JSON.stringify(task_running[i]['task']) + 
                                "</li>" +
                                "<div class='hidden meta' id=" + meta_str + ">"+
                                JSON.stringify(task_running[i]['meta']) + 
                                "</div>" 
            );
            if ($('#' + meta_str).length) {
                if ($('#' + meta_str).is(':visible')) {
                    ul_running.children().last().last().show();
                } else {
                    ul_running.children().last().last().hide();
                }
            } else {
                ul_running.children().last().last().hide();
            }
            queue_num += 1;
        }

        task_queue = result[2];
        ul_queued = $("<ul class=element>");
        for (var i=0, l=task_queue.length; i<l; ++i) {
            var meta_str = "meta" + queue_num;
            ul_queued.append(
                                "<li class='element queued' data-div=" + meta_str + ">" + 
                                i + ") " + 
                                JSON.stringify(task_queue[i]['task']) + 
                                "</li>" +
                                "<div class='hidden meta' id="+ meta_str + ">" + 
                                JSON.stringify(task_queue[i]['meta']) + 
                                "</div>" 
            );
            if ($('#' + meta_str).length) {
                if ($('#' + meta_str).is(':visible')) {
                    ul_queued.children().last().last().show();
                } else {
                    ul_queued.children().last().last().hide();
                }
            } else {
                ul_queued.children().last().last().hide();
            }
            queue_num += 1;
        }

        $("#history").html(ul_history);
        $("#running").html(ul_running);
        $("#queued").html(ul_queued);

        $('li.element').on('click', function() {
            $('div[id="' + $(this).data('div') + '"]').toggle(); 
        });
        
        $.get('/queue_state', function (data) {
            $("#queue_state").text(data);
        });

        $('#history_size').text(task_history.length);
        $('#queue_size').text(task_queue.length);
        
    })
    $.get( "driver_status", function( result ) {
        ul_status = $("<ul class=element>");
        for (var i=0, l=result.length; i<l; ++i) {
            ul_status.append(
                "<li class='element status'>" + 
                JSON.stringify(result[i]) + 
                "</li>"
            );
        }
        $("#driver_status").html(ul_status);
    })

    var x = new Date()
    $("#time").text(x)

    setTimeout(function () {update()}, 500); // this will run every 0.5 seconds  
};

update(); // This will run on page load
// var updateInteval = setInterval(function(){ update() }, 500); // this will run every 0.5 seconds  


	

