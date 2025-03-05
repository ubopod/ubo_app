import {
  Card,
  CardContent,
  CardActions,
  Button,
  Alert,
  AlertProps,
  AlertTitle,
} from "@mui/material";

interface StatusProps {
  message: string;
  severity?: AlertProps["severity"];
  action?: { callback: () => void; label: string };
}

export function Status({ message, severity = "warning", action }: StatusProps) {
  return (
    <Card>
      <CardContent>
        <Alert severity={severity}>
          <AlertTitle>{message}</AlertTitle>
        </Alert>
      </CardContent>
      {action && (
        <CardActions>
          <Button onClick={action.callback}>{action.label}</Button>
        </CardActions>
      )}
    </Card>
  );
}
