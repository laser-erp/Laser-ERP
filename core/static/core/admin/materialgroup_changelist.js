/**
 * Список групп: плейсхолдер поиска.
 */
(function () {
  "use strict";

  function init() {
    var search = document.querySelector(
      "body.change-list:is(.model-materialgroup, .model-productgroup) .material-cl-search input#searchbar"
    );
    if (search) {
      search.setAttribute("placeholder", "Поиск группы…");
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
