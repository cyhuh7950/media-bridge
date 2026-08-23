import { render, screen } from "@testing-library/react";

import { ConnectionsPage } from "./ConnectionsPage";
import { TestLabPage } from "./TestLabPage";

it.each([
  ["Connections", <ConnectionsPage />],
  ["Test Lab", <TestLabPage />],
])("keeps disabled %s dependency honest and makes no network call", (heading, page) => {
  const fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);

  const { unmount } = render(page);

  expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  expect(screen.getByText("DEPENDENCY_NOT_READY")).toBeInTheDocument();
  expect(screen.getByText(/P3 Gateway/)).toBeInTheDocument();
  expect(screen.queryByText(/연결 성공|시험 성공/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(/파일|미디어|이미지/i)).not.toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
  unmount();
});
