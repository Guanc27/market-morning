// jsc harness: run the REAL render pipeline over generated content.
// Usage: jsc -e 'var MODE="brief",FILE="brief.md"' harness_run.js   (we inline via wrapper)
// Actually invoked as: jsc harness.js -- MODE FILE

// ---- DOM / app-global shims (only what the render closure touches) ----
var _captured = "";
function $(id){ return {
  classList:{ add:function(){}, remove:function(){} },
  set innerHTML(v){ _captured = v; },
  get innerHTML(){ return _captured; },
  querySelectorAll:function(){ return []; },
}; }
function stockLogoHtml(t){ return "<logo:"+t+">"; }
function attachLogoFallbacks(){}
function preloadLogos(){}
function bindButtonPressFeedback(){}
function addWatch(){}
var watchlistTickers = { has:function(){return false;} };
var watchlistPending = { has:function(){return false;} };

// ---- load extracted pipeline ----
load("_render_bundle.js");

// ---- args ----
var MODE = arguments[0];
var FILE = arguments[1];

function renderFile(mode, file){
  var text = readFile(file);
  if (mode === "brief") return mdBrief(text);
  if (mode === "explore") return mdExplore(text);
  if (mode === "portfolio") return mdPortfolio(text);
  if (mode === "inline") return inlineMd(text);
  if (mode === "md") return md(text);
  throw "bad mode "+mode;
}

print(renderFile(MODE, FILE));
