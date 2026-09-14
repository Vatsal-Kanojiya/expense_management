/* Add and remove line-item rows without a round trip.
 *
 * The first JavaScript in this project, and deliberately the smallest thing
 * that does the job: no framework, no build step, no dependency. Everything
 * here is additive. With the file blocked or broken the form still works --
 * you get the blank rows Django rendered and the DELETE checkboxes, which is
 * why the buttons ship with `hidden` set and are revealed only once this runs.
 */
(function () {
  "use strict";

  document.querySelectorAll("[data-formset]").forEach(setUp);

  function setUp(root) {
    var prefix = root.dataset.formset;
    var rows = root.querySelector("[data-formset-rows]");
    var blank = root.querySelector("[data-formset-blank]");
    var addButton = root.querySelector("[data-formset-add]");
    var total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");

    // Any of these missing means the markup is not what this script expects.
    // Leaving the page in its no-JavaScript state beats half-enhancing it.
    if (!rows || !blank || !addButton || !total) {
      return;
    }

    addButton.hidden = false;
    revealControls(rows);

    addButton.addEventListener("click", function () {
      // TOTAL_FORMS counts the forms already rendered, so it is also the
      // index the next one needs. Django reads it back to decide how many
      // forms to build from the POST; forget to raise it and the new row is
      // silently ignored.
      var index = Number(total.value);

      rows.insertAdjacentHTML("beforeend", blank.innerHTML.split("__prefix__").join(index));
      total.value = index + 1;

      var added = rows.lastElementChild;
      revealControls(added);

      var first = added.querySelector("input:not([type=hidden]), select, textarea");
      if (first) {
        first.focus();
      }
    });

    // One listener on the table body rather than one per button, so rows
    // added later are covered without rebinding anything.
    rows.addEventListener("click", function (event) {
      var button = event.target.closest("[data-formset-remove]");
      if (button) {
        removeRow(button.closest("[data-formset-row]"));
      }
    });
  }

  function revealControls(scope) {
    scope.querySelectorAll("[data-formset-remove]").forEach(function (button) {
      button.hidden = false;
    });
    // The checkbox and the button are two routes to the same outcome. Once
    // the button works, showing both would only raise the question of which
    // one is the real control.
    scope.querySelectorAll("[data-formset-delete]").forEach(function (label) {
      label.hidden = true;
    });
  }

  function removeRow(row) {
    var flag = row.querySelector('input[name$="-DELETE"]');

    if (flag) {
      // A saved row cannot simply disappear. Django deletes it only when its
      // DELETE flag comes back ticked, and the hidden id field has to be
      // posted alongside for the formset to know which row is meant -- so the
      // row stays in the document and is merely hidden.
      flag.checked = true;
      row.hidden = true;
      return;
    }

    // An unsaved row has no database row behind it, so it is emptied instead.
    // Tearing it out of the DOM would leave a gap in the index sequence, and
    // closing that gap means rewriting the name, id and label of every field
    // on every surviving row. Blanking costs nothing instead: a formset skips
    // an extra form that comes back unchanged, so an empty row is no row.
    row.querySelectorAll("input, select, textarea").forEach(function (field) {
      if (field.type === "checkbox" || field.type === "radio") {
        field.checked = false;
      } else if (field.type !== "hidden") {
        field.value = "";
      }
    });
    row.hidden = true;
  }
})();
