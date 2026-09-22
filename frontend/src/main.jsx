import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import HomePage from "./pages/HomePage.jsx";
import ProcessingPage from "./pages/ProcessingPage.jsx";
import ReaderPage from "./pages/ReaderPage.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/works/:id/processing" element={<ProcessingPage />} />
          <Route path="/works/:id" element={<ReaderPage />} />
          {/* Reader views are real URLs now (graph/arcs/timeline/story/raw), so
              they are shareable, survive a reload and work with the back button.
              The static `processing` segment above wins over this dynamic one. */}
          <Route path="/works/:id/:view" element={<ReaderPage />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>
);
