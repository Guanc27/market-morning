var _captured="";
function $(id){return{classList:{add:function(){},remove:function(){}},set innerHTML(v){_captured=v;},get innerHTML(){return _captured;},querySelectorAll:function(){return[];}};}
function stockLogoHtml(t){return"<logo:"+t+">";}
function attachLogoFallbacks(){} function preloadLogos(){} function bindButtonPressFeedback(){} function addWatch(){}
var watchlistTickers={has:function(){return false;}}; var watchlistPending={has:function(){return false;}};
load("_render_bundle.js");

function show(label, input, out){
  print("### "+label);
  print("  IN : "+JSON.stringify(input));
  print("  OUT: "+out);
  print("");
}

// 1. COLON BEFORE LINK — glued and spaced variants
show("colon glued to link", "News:[Chip rally](https://ex.com/a)", inlineMd("News:[Chip rally](https://ex.com/a)"));
show("colon spaced to link", "News: [Chip rally](https://ex.com/a)", inlineMd("News: [Chip rally](https://ex.com/a)"));
show("bold label colon glued to link", "**News:**[Chip rally](https://ex.com/a)", inlineMd("**News:**[Chip rally](https://ex.com/a)"));
show("bold label colon glued to word", "**Thesis:**You buy", inlineMd("**Thesis:**You buy"));
show("plain colon glued to word", "Impact:tickers move", inlineMd("Impact:tickers move"));
show("time ratio not touched", "at 10:30 a 3:1 ratio", inlineMd("at 10:30 a 3:1 ratio"));
show("url colon not touched", "see https://ex.com:8080/x now", inlineMd("see https://ex.com:8080/x now"));

// 2. GLUED BOLD
show("word glued bold", "positioning.**Buy** now", inlineMd("positioning.**Buy** now"));
show("bold glued word", "the **catalyst**drives it", inlineMd("the **catalyst**drives it"));
show("bold glued bracket", "gain**[link](https://ex.com/z)", inlineMd("gain**[link](https://ex.com/z)"));

// 3. AMP ENCODING in query-string link
show("ampersand in url", "[go](https://ex.com/x?g=1&mod=rss&z=2)", inlineMd("[go](https://ex.com/x?g=1&mod=rss&z=2)"));

// 4. EM-DASH glued
show("emdash glued words", "chips affected—tickers move", inlineMd("chips affected—tickers move"));
show("emdash numeric range kept", "the 2024—2025 window", inlineMd("the 2024—2025 window"));
show("bold label emdash", "**Tickers affected**—NVDA", inlineMd("**Tickers affected**—NVDA"));

// 5. ORDERED LIST glued marker -> bold-numbered <ol>
show("ol glued to bold", "1.**Trim NVDA** on the cross\n2.**Add TSM** here", md("1.**Trim NVDA** on the cross\n2.**Add TSM** here"));
show("ol normal", "1. First item\n2. Second item", md("1. First item\n2. Second item"));

// 6. non-https link dropped
show("http (non-s) link", "[x](http://ex.com/a)", inlineMd("[x](http://ex.com/a)"));
show("javascript link dropped", "[x](javascript:alert(1))", inlineMd("[x](javascript:alert(1))"));

// 7. glossary first-occurrence only (document scope via md)
show("glossary dedup", "RSI is high. Later RSI again and RSI more.", md("RSI is high. Later RSI again and RSI more."));

// 8. watchlist adds — ticker cleanliness
print("### renderWatchlistAdds LMND");
renderWatchlistAdds({watchlist_adds:[{ticker:"LMND",reason:"AI insurtech **momentum** breakout"},{ticker:"ACHR",reason:"eVTOL catalyst"}]});
print(_captured);
print("");
