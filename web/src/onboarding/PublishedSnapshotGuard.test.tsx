import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { PublishedSnapshotGuard } from "./PublishedSnapshotGuard";

function jsonResponse(body: object): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

it("blocks the dashboard until a real snapshot exists", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(jsonResponse([])));

  render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route element={<PublishedSnapshotGuard />}>
          <Route path="/" element={<h1>Dashboard</h1>} />
        </Route>
        <Route path="/setup" element={<h1>온보딩</h1>} />
      </Routes>
    </MemoryRouter>,
  );

  expect(await screen.findByRole("heading", { name: "온보딩" })).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Dashboard" })).not.toBeInTheDocument();
});
