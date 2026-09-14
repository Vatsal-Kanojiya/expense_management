/* Keeps the expense form heading and the browser tab title in step with the
 * note field while it is typed.
 *
 * The server renders the right heading on load (the note, or "New expense" /
 * "Edit expense" when there is none), so without JavaScript nothing is lost --
 * the heading just stops following keystrokes.
 */
(function () {
  "use strict";

  var heading = document.getElementById("expense-heading");
  var note = document.getElementById("id_note");

  if (!heading || !note) {
    return;
  }

  var fallback = heading.getAttribute("data-fallback");
  var suffix = " · Expense Tracker";

  function sync() {
    var text = note.value.trim() || fallback;
    // textContent, not innerHTML: the note is user input.
    heading.textContent = text;
    document.title = text + suffix;
  }

  note.addEventListener("input", sync);
  sync();
})();
