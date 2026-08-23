import { AuthProvider } from "../auth/AuthProvider";
import { ConsoleRouter } from "./router";

export function App() {
  return <AuthProvider><ConsoleRouter /></AuthProvider>;
}
