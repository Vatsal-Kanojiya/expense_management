/* Progressive enhancement for Details and Split tabs on the expense edit page.
 *
 * Both panels ship in the HTML. On load, this script hides the split panel
 * and reveals the tab bar (which ships with `hidden`).
 */
(function () {
  "use strict";

  var tabBar = document.querySelector(".tab-bar");
  var tabDetails = document.getElementById("tab-details");
  var tabSplit = document.getElementById("tab-split");
  var panelDetails = document.getElementById("panel-details");
  var panelSplit = document.getElementById("panel-split");

  if (!tabBar || !tabDetails || !tabSplit || !panelDetails || !panelSplit) {
    return;
  }

  // Progressive enhancement: reveal the tab bar and hide the split panel
  tabBar.hidden = false;
  panelSplit.hidden = true;

  function selectTab(selectedTab, activePanel, unselectedTab, inactivePanel) {
    selectedTab.setAttribute("aria-selected", "true");
    selectedTab.classList.add("is-active");
    unselectedTab.setAttribute("aria-selected", "false");
    unselectedTab.classList.remove("is-active");

    activePanel.hidden = false;
    inactivePanel.hidden = true;
  }

  tabDetails.addEventListener("click", function () {
    selectTab(tabDetails, panelDetails, tabSplit, panelSplit);
  });

  tabSplit.addEventListener("click", function () {
    selectTab(tabSplit, panelSplit, tabDetails, panelDetails);
  });
})();
