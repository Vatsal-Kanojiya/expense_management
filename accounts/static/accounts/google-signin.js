"use strict";

/*
 * Sign in with Google -- the callback-mode receiver (docs/design/GOOGLE_SIGNIN.md).
 *
 * Google Identity Services (loaded from https://accounts.google.com/gsi/client
 * by the login/sign-up templates) calls handleGoogleCredential() with the
 * signed ID token once someone picks an account -- callback mode, never
 * redirect mode, so the token never leaves this page's own origin. This
 * file posts it straight back to our own view with the page's CSRF token,
 * exactly like any other form on this site, and follows the redirect the
 * view answers with.
 *
 * A static file, not an inline <script>, so the page's Content-Security-Policy
 * needs no 'unsafe-inline' for script-src (config/middleware.py).
 */

// From the page, not the cookie: in production the cookie is named
// __Host-csrftoken (config/settings.py), so reading it by a fixed name breaks.
function googleSigninCsrfToken() {
  var mount = document.getElementById("google-signin-mount");
  return mount ? mount.dataset.csrfToken || "" : "";
}

function handleGoogleCredential(response) {
  var mount = document.getElementById("google-signin-mount");
  var postUrl = mount ? mount.dataset.postUrl : "/accounts/google/";
  var nextField = document.querySelector('input[name="next"]');
  var next = nextField ? nextField.value : "";

  var body = new URLSearchParams();
  body.set("credential", response.credential);
  body.set("next", next);

  fetch(postUrl, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "X-CSRFToken": googleSigninCsrfToken(),
    },
    body: body.toString(),
  })
    .then(function (res) {
      // The view always answers with a redirect; fetch follows it, and
      // res.url is wherever that chain ended up.
      window.location.assign(res.url || "/");
    })
    .catch(function () {
      window.location.assign(postUrl);
    });
}

// eslint-disable-next-line no-unused-vars -- called by Google's own script via data-callback.
window.handleGoogleCredential = handleGoogleCredential;
