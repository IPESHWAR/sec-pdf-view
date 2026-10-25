const fs = require("fs");
const path = require("path");

const viewerUrl = fs
  .readFileSync(path.join(__dirname, "viewer-url.txt"), "utf8")
  .trim();

let hostname = "";
try {
  hostname = new URL(viewerUrl).hostname;
} catch (error) {
  throw new Error(
    "mobile/viewer-url.txt must contain one absolute URL, for example http://192.168.1.20:5000"
  );
}

/** @type {import('@capacitor/cli').CapacitorConfig} */
const config = {
  appId: "com.mysec.viewer",
  appName: "MySec Viewer",
  webDir: "www",
  server: {
    // The WebView's top-level document is the Python viewer, so the password
    // form, session cookie, and Rebin watermark stay the ones server.py sends.
    url: viewerUrl,
    cleartext: true,
    allowNavigation: hostname ? [hostname] : [],
  },
  android: {
    allowMixedContent: false,
  },
  ios: {
    contentInset: "automatic",
    limitsNavigationsToAppBoundDomains: false,
  },
};

module.exports = config;
