/* Live calculation of unaccounted amount under the line-item table.
 *
 * Read-only display: never writes to the misc field or alters form inputs.
 * Hides when the difference is under 1.00 rupee.
 */
(function () {
  "use strict";

  // Start from the indicator and walk up to its own form. The first <form>
  // on the page is the logout button in the header, which has no amount
  // fields, so querySelector("form") silently disabled this whole script.
  var indicator = document.getElementById("expense-unaccounted");
  var form = indicator && indicator.closest("form");

  if (!form || !indicator) {
    return;
  }

  function parseAmount(val) {
    var num = parseFloat(val);
    return isNaN(num) ? 0 : num;
  }

  function updateTotals() {
    var amountInput = form.querySelector('input[name="amount"]');
    var miscInput = form.querySelector('input[name="misc_amount"]');

    if (!amountInput) {
      return;
    }

    var totalAmount = parseAmount(amountInput.value);
    var miscAmount = parseAmount(miscInput ? miscInput.value : 0);

    var rows = form.querySelectorAll("[data-formset-rows] [data-formset-row]");
    var itemsTotal = 0;
    var hasItems = false;

    rows.forEach(function (row) {
      var del = row.querySelector('input[name$="-DELETE"]');
      if (del && del.checked) {
        return;
      }
      var amountField = row.querySelector('input[name$="-amount"]');
      if (amountField && amountField.value.trim() !== "") {
        hasItems = true;
        itemsTotal += parseAmount(amountField.value);
      }
    });

    if (!hasItems) {
      indicator.hidden = true;
      indicator.textContent = "";
      return;
    }

    var diff = totalAmount - itemsTotal - miscAmount;

    if (Math.abs(diff) < 1.0) {
      indicator.hidden = true;
      indicator.textContent = "";
    } else if (diff >= 1.0) {
      indicator.hidden = false;
      indicator.textContent = "₹" + diff.toFixed(2) + " not accounted for";
    } else {
      indicator.hidden = false;
      indicator.textContent = "₹" + Math.abs(diff).toFixed(2) + " over the total";
    }
  }

  form.addEventListener("input", updateTotals);
  form.addEventListener("change", updateTotals);
  form.addEventListener("click", function (event) {
    if (event.target.closest("[data-formset-remove]")) {
      setTimeout(updateTotals, 0);
    }
  });

  updateTotals();
})();
