$('#server-menu').menu(
  //{"position":{'my':'center bottom','at':'top'}}
)
$('#view-menu').menu(
  //{"position":{'my':'center bottom','at':'top'}}
)

$(document).ready(function() {
    $("#server-btn").click(function() {
          $("#server-menu").toggleClass("open", 1000) 
    })
    $("#view-btn").click(function() {
          $("#view-menu").toggleClass("open", 1000) 
    })
    
});


