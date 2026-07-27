import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import HomePage from "./pages/HomePage.jsx";
import ProcessingPage from "./pages/ProcessingPage.jsx";
import ReaderPage from "./pages/ReaderPage.jsx";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/works/:id/processing" element={<ProcessingPage />} />
        <Route path="/works/:id" element={<ReaderPage />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
