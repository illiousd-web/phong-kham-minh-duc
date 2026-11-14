// Browser APIs used by the classic scripts; no Node.js globals.
const browserGlobals = Object.fromEntries([
    "window", "document", "navigator", "location", "sessionStorage", "localStorage",
    "fetch", "FormData", "URL", "URLSearchParams", "Blob", "File", "FileReader",
    "crypto", "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame", "console", "alert", "confirm",
    "prompt", "getComputedStyle", "MutationObserver", "ResizeObserver", "CSS",
    "scrollY", "innerHeight", "HTMLElement", "Event", "CustomEvent", "AbortController", "performance",
].map(name => {
    return [name, "readonly"];
}));

// index.html:30-32 loads app.js, m6.js and m5.js as deferred classic scripts.
// Declare only names actually provided by the other scripts, per consumer file.
const sharedGlobals = {
    "app/static/app.js": ["M5", "M6"],
    "app/static/m5.js": [
        "LABEL", "M6", "SCREENS", "api", "auth", "authHeader", "cap", "card",
        "esc", "labelTables", "menus", "notify", "parseDay", "render",
        "scopeWarnings", "sel", "showDay", "t",
    ],
    "app/static/m6.js": [
        "SCREENS", "api", "auth", "authHeader", "boot", "cap", "card", "empty",
        "esc", "menus", "notify", "render", "t",
    ],
};

module.exports = [{
    files: ["app/static/*.js"],
    languageOptions: {
        ecmaVersion: 2022,
        sourceType: "script",
        globals: browserGlobals,
    },
    rules: {
        "no-undef": "error",
        "no-dupe-keys": "error",
        "no-redeclare": "error",
        "no-unreachable": "error",
        "no-dupe-else-if": "error",
        "no-self-assign": "error",
        "no-unused-vars": ["error", {args: "none"}],
    },
}, ...Object.entries(sharedGlobals).map(([file, names]) => ({
    files: [file],
    languageOptions: {
        globals: Object.fromEntries(names.map(name => {
            return [name, "readonly"];
        })),
    },
})), {
    files: ["app/static/app.js"],
    rules: {
        "no-unused-vars": ["error", {
            args: "none",
            // Legacy exceptions: app/static/* must remain unchanged in this task.
            // app.js:23 patientList, dueList: unused state; retained without changing UI code.
            // app.js:124 patientHead: unused renderer; retained for the same scope restriction.
            // app.js:233 groups: unused derived list; retained without changing UI code.
            // app.js:249 visits: unused merged list; preserve the surrounding API calls.
            // app.js:707 boot: called by m6.js:62 after all deferred scripts have loaded.
            varsIgnorePattern: "^(patientList|dueList|patientHead|groups|visits|boot)$",
            // app.js:146,151,276 e: intentionally unused catch bindings; preserve handlers.
            caughtErrorsIgnorePattern: "^e$",
        }],
    },
}];
