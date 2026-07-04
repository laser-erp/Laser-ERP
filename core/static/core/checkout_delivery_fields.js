(function () {
  "use strict";

  function byName(name) {
    return document.querySelectorAll('input[name="' + name + '"]');
  }

  function value(name) {
    var radios = byName(name);
    for (var i = 0; i < radios.length; i += 1) {
      if (radios[i].checked) {
        return radios[i].value;
      }
    }
    return "";
  }

  function init() {
    var form = document.querySelector('form[action=""]') || document.querySelector("form");
    if (!form) {
      return;
    }
    var address = form.querySelector('input[name="delivery_address"]');
    var city = form.querySelector('input[name="delivery_city"]');
    var company = form.querySelector('input[name="transport_company"]');
    if (!address || !city || !company) {
      return;
    }

    function toggle() {
      var method = value("delivery_method");
      var courier = method === "courier";
      var tc = method === "transport_company";

      address.required = courier;
      city.required = tc;
      company.required = tc;

      address.disabled = !courier;
      city.disabled = !tc;
      company.disabled = !tc;
    }

    var radios = byName("delivery_method");
    for (var i = 0; i < radios.length; i += 1) {
      radios[i].addEventListener("change", toggle);
    }
    toggle();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
