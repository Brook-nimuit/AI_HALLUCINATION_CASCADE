import React, { useMemo } from "react";
import { createRoot } from "react-dom/client";
import { Chess } from "chess.js";
import { Chessboard } from "react-chessboard";
import "./chess-review.css";

const LEGAL_LIGHT_SQUARE = "#EEEED2";
const LEGAL_DARK_SQUARE = "#769656";
const LAST_MOVE_HIGHLIGHT = "rgba(255, 255, 0, 0.42)";
const ILLEGAL_ARROW = "#d63b35";

function isSquare(square) {
  return typeof square === "string" && /^[a-h][1-8]$/.test(square);
}

function getReviewPosition(pgn, moves, selectedPly) {
  const game = new Chess();
  const legalMoves = moves.filter(
    (move) => move.status === "LEGAL" && move.ply <= selectedPly,
  );

  if (pgn) {
    const parsedPgn = new Chess();
    parsedPgn.loadPgn(pgn);
    const pgnMoves = parsedPgn.history();
    if (pgnMoves.length < legalMoves.length) {
      throw new Error("The stored PGN is missing audited legal moves.");
    }
    legalMoves.forEach((move, index) => game.move(pgnMoves[index]));
  } else {
    legalMoves.forEach((move) => game.move(move.san));
  }

  const history = game.history({ verbose: true });
  return {
    fen: game.fen(),
    lastMove: history.at(-1) ?? null,
  };
}

function getIllegalSquares(illegalMove) {
  const coordinates = illegalMove?.illegal_move;
  if (isSquare(coordinates?.from_square) && isSquare(coordinates?.to_square)) {
    return [coordinates.from_square, coordinates.to_square];
  }

  const castling = (illegalMove?.san ?? "").replaceAll("0", "O");
  if (castling === "O-O" || castling === "O-O-O") {
    const rank = illegalMove.actor === "Black" ? "8" : "1";
    return [`e${rank}`, `${castling === "O-O" ? "g" : "c"}${rank}`];
  }

  const description = String(illegalMove?.reason ?? "");
  const match = description.match(/\b([a-h][1-8])\s*(?:\u2192|->)\s*([a-h][1-8])\b/i);
  return match ? [match[1].toLowerCase(), match[2].toLowerCase()] : [null, null];
}

function ChessReview({ review }) {
  const moves = Array.isArray(review.moves) ? review.moves : [];
  const currentMove = moves.find(
    (move) => move.ply === review.selectedPly && move.status === "ILLEGAL",
  );
  const illegalMove = review.isIllegal
    ? review.illegalMove ?? currentMove ?? null
    : null;

  const position = useMemo(() => {
    try {
      return {
        ...getReviewPosition(review.pgn, moves, review.selectedPly),
        error: "",
      };
    } catch (error) {
      return {
        fen: new Chess().fen(),
        lastMove: null,
        error: error instanceof Error ? error.message : "Could not load this PGN.",
      };
    }
  }, [review.pgn, review.selectedPly, moves]);

  const [illegalFrom, illegalTo] = getIllegalSquares(illegalMove);
  const arrows =
    illegalFrom && illegalTo
      ? [{ startSquare: illegalFrom, endSquare: illegalTo, color: ILLEGAL_ARROW }]
      : [];
  const squareStyles = {};
  if (position.lastMove && !illegalMove) {
    squareStyles[position.lastMove.from] = { backgroundColor: LAST_MOVE_HIGHLIGHT };
    squareStyles[position.lastMove.to] = { backgroundColor: LAST_MOVE_HIGHLIGHT };
  }
  if (illegalTo) {
    squareStyles[illegalTo] = {
      backgroundColor: "rgba(220, 38, 38, 0.3)",
      boxShadow: "inset 0 0 0 4px rgba(153, 27, 27, 0.9)",
    };
  }

  const squareRenderer = ({ square, children }) => (
    <div className="review-square" style={squareStyles[square]}>
      {children}
      {illegalTo === square && (
        <span className="illegal-blunder-sticker" aria-label="Illegal move">
          !!!!!!
        </span>
      )}
    </div>
  );

  return (
    <div className="chess-review">
      <div className="chess-review-board">
        <Chessboard
          options={{
            position: position.fen,
            boardOrientation: "white",
            allowDragging: false,
            allowDrawingArrows: false,
            showAnimations: true,
            animationDurationInMs: 180,
            clearArrowsOnPositionChange: false,
            arrows,
            squareStyles,
            squareRenderer,
            lightSquareStyle: { backgroundColor: LEGAL_LIGHT_SQUARE },
            darkSquareStyle: { backgroundColor: LEGAL_DARK_SQUARE },
            boardStyle: {
              width: "100%",
              borderRadius: "4px",
              overflow: "hidden",
              boxShadow: "0 5px 15px rgba(0, 0, 0, 0.35)",
            },
          }}
        />
      </div>
      {position.error && (
        <div className="chess-review-error" role="alert">
          {position.error}
        </div>
      )}
      {illegalMove && (
        <div className="chess-review-illegal" role="status">
          <strong>Illegal move</strong>
          <span>
            {illegalMove.actor} attempted {illegalMove.san || "an unparseable move"}
          </span>
          {!illegalFrom || !illegalTo ? (
            <span>Move squares could not be inferred from this legacy audit.</span>
          ) : null}
        </div>
      )}
    </div>
  );
}

const mount = document.getElementById("chessboardRoot");
const root = createRoot(mount);

window.renderChessReview = (review) => {
  root.render(<ChessReview review={review} />);
};
