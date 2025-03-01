import {
  DarkModeOutlined,
  LightMode,
  SettingsBrightness,
} from "@mui/icons-material";
import {
  styled,
  SupportedColorScheme,
  ToggleButton,
  ToggleButtonGroup,
  useColorScheme,
} from "@mui/material";

const IconToggleButton = styled(ToggleButton)({
  display: "flex",
  justifyContent: "center",
  width: "100%",
  "& > *": {
    marginRight: "8px",
  },
});

export function ThemeSwitch() {
  const { mode, setMode } = useColorScheme();

  const handleChangeThemeMode = (
    _: React.MouseEvent,
    paletteMode: SupportedColorScheme,
  ) => {
    if (paletteMode === null) {
      return;
    }
    setMode(paletteMode);
  };

  return (
    <ToggleButtonGroup
      exclusive
      value={mode}
      color="primary"
      onChange={handleChangeThemeMode}
      aria-labelledby="settings-mode"
      fullWidth
    >
      <IconToggleButton value="light">
        <LightMode fontSize="small" />
        Light
      </IconToggleButton>
      <IconToggleButton value="system">
        <SettingsBrightness fontSize="small" />
        System
      </IconToggleButton>
      <IconToggleButton value="dark">
        <DarkModeOutlined fontSize="small" />
        Dark
      </IconToggleButton>
    </ToggleButtonGroup>
  );
}
