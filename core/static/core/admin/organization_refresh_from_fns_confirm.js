(function () {
  "use strict";

  function init() {
    var trigger = document.getElementById("organization-refresh-from-fns-btn");
    if (!trigger) {
      return;
    }
    trigger.title = "Обновить данные контрагента из базы ФНС на текущую дату.";
    trigger.addEventListener("click", function (event) {
      var ok = window.confirm(
        "Обновить данные контрагента из базы ФНС на текущую дату?"
      );
      if (!ok) {
        event.preventDefault();
        return;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
