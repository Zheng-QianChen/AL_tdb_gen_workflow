const pathData = {
  grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  layers:'m12 3 9 5-9 5-9-5z M3 12l9 5 9-5 M3 16l9 5 9-5',
  cpu:'M7 7h10v10H7z M10 3v4m4-4v4m-4 10v4m4-4v4M3 10h4m-4 4h4m10-4h4m-4 4h4',
  records:'M6 3h10l3 3v15H6z M9 9h7 M9 13h7 M9 17h4',
  model:'m4 8 8-5 8 5v9l-8 4-8-4z M4 8l8 5 8-5 M12 13v8',
  box:'m3 9 9-5 9 5-9 5z M3 9v8l9 5 9-5V9 M12 14v8 M8 6l9 5',
  arrow:'M4 12h15m-6-6 6 6-6 6',chev:'m9 5 7 7-7 7',check:'m4 12 5 5L20 6',
  plus:'M12 4v16M4 12h16',reset:'M3 10a9 9 0 1 1 1 8 M3 4v6h6',
  warn:'m12 3 10 17H2z M12 9v5 M12 17v.6', clock:'M12 3a9 9 0 1 0 .1 0 M12 7v5l3 2',
  scan:'M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6 M7 12l3 3 6-7',
  file:'M5 3h9l5 5v13H5z M14 3v6h5',edit:'m4 16 11-11 4 4L8 20l-5 1z M12 8l4 4',
  download:'M12 3v12m-5-5 5 5 5-5 M4 16v5h16v-5',close:'M5 5l14 14M19 5 5 19',
  branch:'M6 4v16 M6 14c0-5 11-2 11-9 M4 3h4v3H4z M15 2h4v3h-4z'
};
function icon(name) {
  return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${pathData[name]}"/></svg>`;
}
