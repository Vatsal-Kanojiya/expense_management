/* Searchable multi-select widget with chips.
 *
 * Progressive enhancement for <select multiple>:
 * - The underlying <select> remains the single source of truth for form data.
 * - Chips show selected items and allow quick removal.
 * - A search input filters unselected options in a dropdown.
 * - Without JavaScript, the browser falls back to the native <select multiple>.
 * - Dynamically added rows (e.g. from item-formset.js) are initialized via MutationObserver.
 */
(function () {
  "use strict";

  // Initialise widgets already in the document
  document.querySelectorAll("[data-chip-select]").forEach(setUpChipSelect);

  // Observe the document for newly inserted rows (e.g. cloned by item-formset.js)
  if (typeof MutationObserver !== "undefined") {
    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            if (node.matches("[data-chip-select]")) {
              setUpChipSelect(node);
            } else if (node.querySelectorAll) {
              node.querySelectorAll("[data-chip-select]").forEach(setUpChipSelect);
            }
          }
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function setUpChipSelect(root) {
    if (root.dataset.chipInitialized) {
      return;
    }
    root.dataset.chipInitialized = "true";

    var select = root.querySelector("select");
    var ui = root.querySelector("[data-chip-ui]");
    var chipList = root.querySelector("[data-chip-list]");
    var searchInput = root.querySelector("[data-chip-search]");
    var dropdown = root.querySelector("[data-chip-dropdown]");

    if (!select || !ui || !chipList || !searchInput || !dropdown) {
      return;
    }

    // Reveal the enhanced UI and hide the raw multi-select
    select.hidden = true;
    ui.hidden = false;

    // Render chips for options that start selected
    renderChips();

    // Open dropdown on search input focus or typing
    searchInput.addEventListener("focus", function () {
      updateDropdown();
    });

    searchInput.addEventListener("input", function () {
      updateDropdown();
    });

    // Close dropdown on click outside
    document.addEventListener("click", function (event) {
      if (!root.contains(event.target)) {
        dropdown.hidden = true;
      }
    });

    // Keyboard navigation in search input
    searchInput.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        dropdown.hidden = true;
      } else if (event.key === "Backspace" && searchInput.value === "") {
        // Backspace on empty query removes the last chip
        var selectedOptions = Array.from(select.options).filter(function (opt) {
          return opt.selected;
        });
        if (selectedOptions.length > 0) {
          selectedOptions[selectedOptions.length - 1].selected = false;
          renderChips();
          select.dispatchEvent(new Event("change", { bubbles: true }));
          updateDropdown();
        }
      }
    });

    // Dropdown item selection
    dropdown.addEventListener("click", function (event) {
      var item = event.target.closest("[data-option-value]");
      if (!item) {
        return;
      }
      var val = item.dataset.optionValue;
      var option = Array.from(select.options).find(function (opt) {
        return opt.value === val;
      });
      if (option) {
        option.selected = true;
        searchInput.value = "";
        renderChips();
        select.dispatchEvent(new Event("change", { bubbles: true }));
        updateDropdown();
        searchInput.focus();
      }
    });

    // Chip removal
    chipList.addEventListener("click", function (event) {
      var removeBtn = event.target.closest("[data-remove-chip]");
      if (!removeBtn) {
        return;
      }
      var val = removeBtn.dataset.removeChip;
      var option = Array.from(select.options).find(function (opt) {
        return opt.value === val;
      });
      if (option) {
        option.selected = false;
        renderChips();
        select.dispatchEvent(new Event("change", { bubbles: true }));
        updateDropdown();
      }
    });

    function renderChips() {
      chipList.innerHTML = "";
      Array.from(select.options).forEach(function (option) {
        if (!option.selected) {
          return;
        }
        var chip = document.createElement("span");
        chip.className = "chip";
        chip.textContent = option.text + " ";

        var removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "chip-remove";
        removeBtn.dataset.removeChip = option.value;
        removeBtn.setAttribute("aria-label", "Remove " + option.text);
        removeBtn.textContent = "\u00d7";

        chip.appendChild(removeBtn);
        chipList.appendChild(chip);
      });
    }

    function updateDropdown() {
      var query = searchInput.value.trim().toLowerCase();
      var available = Array.from(select.options).filter(function (option) {
        if (option.selected) {
          return false;
        }
        if (!query) {
          return true;
        }
        return option.text.toLowerCase().indexOf(query) !== -1;
      });

      if (available.length === 0) {
        dropdown.innerHTML = '<div class="chip-empty">No options</div>';
        dropdown.hidden = false;
        return;
      }

      dropdown.innerHTML = "";
      available.forEach(function (option) {
        var item = document.createElement("div");
        item.className = "chip-dropdown-item";
        item.dataset.optionValue = option.value;
        item.textContent = option.text;
        dropdown.appendChild(item);
      });
      dropdown.hidden = false;
    }
  }
})();
