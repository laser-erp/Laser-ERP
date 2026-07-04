(function () {
  function getCookie(name) {
    var value = "; " + document.cookie;
    var parts = value.split("; " + name + "=");
    if (parts.length === 2) {
      return parts.pop().split(";").shift();
    }
    return "";
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatChatText(text) {
    var escaped = escapeHtml(text);
    var linked = escaped.replace(
      /(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>'
    );
    return linked.replace(/\n/g, "<br>");
  }

  function renderMessages(container, messages) {
    if (!messages.length) {
      container.innerHTML = '<div class="text-muted">Пока сообщений нет.</div>';
      return;
    }
    var html = "";
    for (var i = 0; i < messages.length; i += 1) {
      var msg = messages[i];
      var text = formatChatText(msg.text);
      html +=
        '<div class="mb-2 js-chat-item">' +
        '<div class="text-muted" style="font-size: 12px;">' +
        escapeHtml(msg.created_at) +
        " — " +
        escapeHtml(msg.author_label);
      if (msg.can_edit && msg.edit_url) {
        html +=
          ' <button type="button" class="btn btn-link p-0 ms-1 align-baseline text-secondary js-chat-edit-btn" style="font-size:11px;line-height:1;text-decoration:none;" title="Редактировать" aria-label="Редактировать сообщение" data-edit-url="' +
          escapeHtml(msg.edit_url) +
          '" data-current="' +
          escapeHtml(msg.text) +
          '">&#9999;</button>';
      }
      html +=
        "</div>" +
        '<div class="js-chat-text">' +
        text +
        "</div>" +
        "</div>";
    }
    container.innerHTML = html;
    container.scrollTop = container.scrollHeight;
  }

  function initChat(block) {
    var fetchUrl = block.getAttribute("data-fetch-url");
    var postUrl = block.getAttribute("data-post-url");
    var listEl = block.querySelector(".js-chat-messages");
    var formEl = block.querySelector(".js-chat-form");
    var inputEl = block.querySelector('input[name="text"]');
    var submitEl = formEl ? formEl.querySelector('button[type="submit"]') : null;
    var isEditing = false;

    if (!fetchUrl || !postUrl || !listEl || !formEl || !inputEl) {
      return;
    }

    function refresh() {
      if (isEditing) {
        return;
      }
      fetch(fetchUrl, { credentials: "same-origin" })
        .then(function (resp) {
          if (!resp.ok) {
            throw new Error("fetch failed");
          }
          return resp.json();
        })
        .then(function (data) {
          renderMessages(listEl, data.messages || []);
        })
        .catch(function () {
          // Ignore transient network errors on polling.
        });
    }

    formEl.addEventListener("submit", function (event) {
      event.preventDefault();
      var text = (inputEl.value || "").trim();
      if (!text) {
        return;
      }
      if (submitEl) {
        submitEl.disabled = true;
      }
      var formData = new FormData();
      formData.append("text", text);

      fetch(postUrl, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": getCookie("csrftoken"),
        },
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.data.ok) {
            throw new Error(result.data.error || "send failed");
          }
          inputEl.value = "";
          refresh();
        })
        .catch(function (err) {
          alert(err.message || "Не удалось отправить сообщение.");
        })
        .finally(function () {
          if (submitEl) {
            submitEl.disabled = false;
          }
        });
    });

    listEl.addEventListener("click", function (event) {
      var editBtn = event.target.closest(".js-chat-edit-btn");
      if (editBtn) {
        event.preventDefault();
        var editItem = editBtn.closest(".js-chat-item");
        var editTextEl = editItem ? editItem.querySelector(".js-chat-text") : null;
        var current = editBtn.getAttribute("data-current") || "";
        if (!editTextEl) {
          return;
        }
        isEditing = true;
        editTextEl.innerHTML =
          '<div class="input-group input-group-sm">' +
          '<input type="text" class="form-control js-chat-edit-input" value="' +
          escapeHtml(current) +
          '">' +
          '<button type="button" class="btn btn-success js-chat-edit-save">OK</button>' +
          '<button type="button" class="btn btn-outline-secondary js-chat-edit-cancel">Отмена</button>' +
          "</div>";
        var focusInput = editTextEl.querySelector(".js-chat-edit-input");
        if (focusInput) {
          focusInput.focus();
          focusInput.setSelectionRange(focusInput.value.length, focusInput.value.length);
        }
        return;
      }

      var saveBtn = event.target.closest(".js-chat-edit-save");
      if (saveBtn) {
        event.preventDefault();
        var saveItem = saveBtn.closest(".js-chat-item");
        var sourceEditBtn = saveItem ? saveItem.querySelector(".js-chat-edit-btn") : null;
        var saveInput = saveItem ? saveItem.querySelector(".js-chat-edit-input") : null;
        if (!sourceEditBtn || !saveInput) {
          isEditing = false;
          refresh();
          return;
        }
        var updated = (saveInput.value || "").trim();
        if (!updated) {
          alert("Текст сообщения не должен быть пустым.");
          return;
        }
        var editUrl = sourceEditBtn.getAttribute("data-edit-url");
        var formData = new FormData();
        formData.append("text", updated);
        fetch(editUrl, {
          method: "POST",
          body: formData,
          credentials: "same-origin",
          headers: {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": getCookie("csrftoken"),
          },
        })
          .then(function (resp) {
            return resp.json().then(function (data) {
              return { ok: resp.ok, data: data };
            });
          })
          .then(function (result) {
            if (!result.ok || !result.data.ok) {
              throw new Error(result.data.error || "edit failed");
            }
            isEditing = false;
            refresh();
          })
          .catch(function (err) {
            alert(err.message || "Не удалось изменить сообщение.");
          });
        return;
      }

      var cancelBtn = event.target.closest(".js-chat-edit-cancel");
      if (cancelBtn) {
        event.preventDefault();
        isEditing = false;
        refresh();
        return;
      }
    });

    refresh();
    setInterval(refresh, 8000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var chats = document.querySelectorAll(".js-production-chat");
    for (var i = 0; i < chats.length; i += 1) {
      initChat(chats[i]);
    }
  });
})();
