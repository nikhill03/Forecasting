// Chart palette shared by ForecastChart and RealizedChart, so a series keeps
// its colour wherever it appears.
export const COLOR_AXIS_LINE  = "#252D48";
export const COLOR_AXIS_TEXT  = "#616B93";
export const COLOR_LEGEND     = "#99A2C4";
export const COLOR_TOOLTIP_BG = "#1B2238";
export const COLOR_TEXT       = "#EEF0F7";
export const COLOR_BOUNDARY   = "#39456B";

export const COLOR_ACTUAL          = "#99A2C4";
export const COLOR_TEST_ACTUAL     = "#7C9CF2";
export const COLOR_TEST_PREDICTION = "#F5C451";
export const COLOR_FORECAST        = "#E8A23D";

// The user's Action Center edits. Violet because the existing amber and yellow
// can't be told apart: validate_palette puts amber↔yellow at ΔE 8.6 under
// normal vision (floor 15), while violet↔amber is 26 and clears the CVD check.
export const COLOR_ADJUSTED = "#B58CF0";
