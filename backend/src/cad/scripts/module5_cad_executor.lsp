; ============================================================================
; Module5 CAD-DXF executor for AcCoreConsole
; ============================================================================
; Python builds runtime .scr and calls these functions in order:
;   module5-reset
;   module5-set-plot-config
;   module5-run-frame / module5-run-sheet-set (many times)
;   module5-finalize
; ============================================================================

(vl-load-com)

(setq *m5-result-path* "")
(setq *m5-job-id* "unknown")
(setq *m5-source-dxf* "")
(setq *m5-log-path* "")

(setq *m5-output-dir* "")
(setq *m5-pc3* "DWG To PDF.pc3")
(setq *m5-ctb* "monochrome.ctb")
(setq *m5-use-monochrome* T)
(setq *m5-margin-top* 20.0)
(setq *m5-margin-bottom* 10.0)
(setq *m5-margin-left* 20.0)
(setq *m5-margin-right* 10.0)
(setq *m5-bbox-margin* 0.015)
(setq *m5-retry-margin* 0.03)

(setq *m5-frame-results* nil)
(setq *m5-sheet-results* nil)
(setq *m5-errors* nil)
(setq *m5-last-wblock-error* "")
(setq *m5-last-plot-error* "")

(defun m5-log (msg / fp)
  (if (and *m5-log-path* (/= *m5-log-path* ""))
    (progn
      (setq fp (open *m5-log-path* "a"))
      (if fp
        (progn
          (write-line msg fp)
          (close fp)
        )
      )
    )
  )
  (princ)
)

(defun m5-json-escape (s)
  (if (null s)
    ""
    (vl-string-subst "\\\"" "\"" (vl-string-subst "\\\\" "\\" s))
  )
)

(defun m5-file-exists (path / fp)
  (if (or (null path) (= path ""))
    nil
    (progn
      (setq fp (open path "r"))
      (if fp
        (progn
          (close fp)
          T
        )
        nil
      )
    )
  )
)

(defun m5-bbox-expand (xmin ymin xmax ymax ratio / w h dx dy)
  (setq w (- xmax xmin))
  (setq h (- ymax ymin))
  (setq dx (* w ratio))
  (setq dy (* h ratio))
  (list (- xmin dx) (- ymin dy) (+ xmax dx) (+ ymax dy))
)

(defun m5-apply-plot-margins (bbox paper-w paper-h / xmin ymin xmax ymax sx sy)
  (setq xmin (nth 0 bbox))
  (setq ymin (nth 1 bbox))
  (setq xmax (nth 2 bbox))
  (setq ymax (nth 3 bbox))
  (setq sx 1.0)
  (setq sy 1.0)
  (if (and (> paper-w 1e-6) (> paper-h 1e-6))
    (progn
      (setq sx (/ (- xmax xmin) paper-w))
      (setq sy (/ (- ymax ymin) paper-h))
    )
  )
  (list
    (- xmin (* *m5-margin-left* sx))
    (- ymin (* *m5-margin-bottom* sy))
    (+ xmax (* *m5-margin-right* sx))
    (+ ymax (* *m5-margin-top* sy))
  )
)

(defun m5-select-crossing (bbox / p1 p2)
  (setq p1 (list (nth 0 bbox) (nth 1 bbox)))
  (setq p2 (list (nth 2 bbox) (nth 3 bbox)))
  (ssget "_C" p1 p2)
)

(defun m5-pt-variant (pt / arr)
  (setq arr (vlax-make-safearray vlax-vbDouble '(0 . 1)))
  (vlax-safearray-fill arr (list (car pt) (cadr pt)))
  (vlax-make-variant arr)
)

(defun m5-ss-to-variant (ss / n arr i)
  (setq n (if ss (sslength ss) 0))
  (if (<= n 0)
    nil
    (progn
      (setq arr (vlax-make-safearray vlax-vbObject (cons 0 (1- n))))
      (setq i 0)
      (while (< i n)
        (vlax-safearray-put-element arr i (vlax-ename->vla-object (ssname ss i)))
        (setq i (1+ i))
      )
      (vlax-make-variant arr)
    )
  )
)

(defun m5-make-flag-json (flag)
  (if (or (null flag) (= flag ""))
    "[]"
    (strcat "[\"" (m5-json-escape flag) "\"]")
  )
)

(defun m5-join-json-lines (items / idx cnt out)
  (setq idx 0)
  (setq cnt (length items))
  (setq out "")
  (foreach it items
    (setq idx (1+ idx))
    (setq out (strcat out it))
    (if (< idx cnt)
      (setq out (strcat out ","))
    )
  )
  out
)

(defun module5-add-error (msg)
  (setq *m5-errors* (append *m5-errors* (list msg)))
  (m5-log (strcat "[ERROR] " msg))
)

(defun module5-add-frame-result (frame-id status pdf-path dwg-path sel-count flag / line)
  (setq line
    (strcat
      "{"
      "\"frame_id\":\"" (m5-json-escape frame-id) "\","
      "\"status\":\"" (m5-json-escape status) "\","
      "\"pdf_path\":\"" (m5-json-escape pdf-path) "\","
      "\"dwg_path\":\"" (m5-json-escape dwg-path) "\","
      "\"selection_count\":" (itoa sel-count) ","
      "\"flags\":" (m5-make-flag-json flag)
      "}"
    )
  )
  (setq *m5-frame-results* (append *m5-frame-results* (list line)))
)

(defun module5-add-sheet-result (cluster-id status pdf-path dwg-path page-count flag / line)
  (setq line
    (strcat
      "{"
      "\"cluster_id\":\"" (m5-json-escape cluster-id) "\","
      "\"status\":\"" (m5-json-escape status) "\","
      "\"pdf_path\":\"" (m5-json-escape pdf-path) "\","
      "\"dwg_path\":\"" (m5-json-escape dwg-path) "\","
      "\"page_count\":" (itoa page-count) ","
      "\"flags\":" (m5-make-flag-json flag)
      "}"
    )
  )
  (setq *m5-sheet-results* (append *m5-sheet-results* (list line)))
)

(defun m5-write-result-json (/ fp frame-json sheet-json errors-json idx cnt)
  (setq fp (open *m5-result-path* "w"))
  (if (not fp)
    (progn
      (m5-log (strcat "[ERROR] cannot write result file: " *m5-result-path*))
    )
    (progn
      (setq frame-json (m5-join-json-lines *m5-frame-results*))
      (setq sheet-json (m5-join-json-lines *m5-sheet-results*))
      (setq errors-json "")
      (if *m5-errors*
        (progn
          (setq idx 0)
          (setq cnt (length *m5-errors*))
          (foreach e *m5-errors*
            (setq idx (1+ idx))
            (setq errors-json (strcat errors-json "\"" (m5-json-escape e) "\""))
            (if (< idx cnt)
              (setq errors-json (strcat errors-json ","))
            )
          )
        )
      )
      (write-line "{" fp)
      (write-line "  \"schema_version\": \"cad-dxf-result@1.0\"," fp)
      (write-line (strcat "  \"job_id\": \"" (m5-json-escape *m5-job-id*) "\"," ) fp)
      (write-line (strcat "  \"source_dxf\": \"" (m5-json-escape *m5-source-dxf*) "\"," ) fp)
      (write-line (strcat "  \"frames\": [" frame-json "],") fp)
      (write-line (strcat "  \"sheet_sets\": [" sheet-json "],") fp)
      (write-line (strcat "  \"errors\": [" errors-json "]") fp)
      (write-line "}" fp)
      (close fp)
    )
  )
)

(defun m5-set-system-vars ()
  (setvar "FILEDIA" 0)
  (setvar "CMDDIA" 0)
  (setvar "SAVEFIDELITY" 0)
  (setvar "BACKGROUNDPLOT" 0)
  (setvar "TILEMODE" 1)
)

(defun m5-media-name (paper-w paper-h / w h)
  (setq w (abs paper-w))
  (setq h (abs paper-h))
  (cond
    ((and (< (abs (- w 1189.0)) 10.0) (< (abs (- h 841.0)) 10.0)) "ISO_A0_(1189.00_x_841.00_MM)")
    ((and (< (abs (- w 841.0)) 10.0) (< (abs (- h 1189.0)) 10.0)) "ISO_A0_(841.00_x_1189.00_MM)")
    ((and (< (abs (- w 841.0)) 10.0) (< (abs (- h 594.0)) 10.0)) "ISO_A1_(841.00_x_594.00_MM)")
    ((and (< (abs (- w 594.0)) 10.0) (< (abs (- h 841.0)) 10.0)) "ISO_A1_(594.00_x_841.00_MM)")
    ((and (< (abs (- w 594.0)) 10.0) (< (abs (- h 420.0)) 10.0)) "ISO_A2_(594.00_x_420.00_MM)")
    ((and (< (abs (- w 420.0)) 10.0) (< (abs (- h 594.0)) 10.0)) "ISO_A2_(420.00_x_594.00_MM)")
    ((and (< (abs (- w 420.0)) 10.0) (< (abs (- h 297.0)) 10.0)) "ISO_A3_(420.00_x_297.00_MM)")
    ((and (< (abs (- w 297.0)) 10.0) (< (abs (- h 420.0)) 10.0)) "ISO_A3_(297.00_x_420.00_MM)")
    ((and (< (abs (- w 297.0)) 10.0) (< (abs (- h 210.0)) 10.0)) "ISO_A4_(297.00_x_210.00_MM)")
    ((and (< (abs (- w 210.0)) 10.0) (< (abs (- h 297.0)) 10.0)) "ISO_A4_(210.00_x_297.00_MM)")
    (T "ISO_A1_(841.00_x_594.00_MM)")
  )
)

(defun m5-orientation-name (paper-w paper-h)
  (if (>= paper-w paper-h) "Landscape" "Portrait")
)

(defun m5-do-wblock (dwg-path ss / cmd-ret)
  (setq *m5-last-wblock-error* "")
  (if (or (null ss) (= (sslength ss) 0))
    nil
    (progn
      (sssetfirst nil ss)
      (setq cmd-ret (vl-catch-all-apply 'command-s (list "_.-WBLOCK" dwg-path "0,0,0" "_P" "")))
      (if (vl-catch-all-error-p cmd-ret)
        (progn
          (setq *m5-last-wblock-error* (vl-catch-all-error-message cmd-ret))
          nil
        )
        (m5-file-exists dwg-path)
      )
    )
  )
)

(defun m5-do-plot (pdf-path bbox paper-w paper-h / p1 p2 media orient cmd-ret)
  (setq *m5-last-plot-error* "PLOT_DISABLED_USE_PYTHON_FALLBACK")
  nil
)

; legacy COM-only implementation retained above by mistake would duplicate symbol definitions.
; keep only the guarded version.
; (defun m5-do-plot ...) replaced.

(defun module5-reset (result-path job-id source-dxf log-path)
  (setq *m5-result-path* result-path)
  (setq *m5-job-id* job-id)
  (setq *m5-source-dxf* source-dxf)
  (setq *m5-log-path* log-path)
  (setq *m5-frame-results* nil)
  (setq *m5-sheet-results* nil)
  (setq *m5-errors* nil)
  (setq *m5-last-wblock-error* "")
  (setq *m5-last-plot-error* "")
  (m5-set-system-vars)
  (m5-log (strcat "[START] job=" job-id " source=" source-dxf))
  (princ)
)

(defun module5-set-plot-config
  (output-dir pc3 ctb use-mono margin-top margin-bottom margin-left margin-right bbox-margin retry-margin)
  (setq *m5-output-dir* output-dir)
  (setq *m5-pc3* pc3)
  (setq *m5-ctb* ctb)
  (setq *m5-use-monochrome* use-mono)
  (setq *m5-margin-top* margin-top)
  (setq *m5-margin-bottom* margin-bottom)
  (setq *m5-margin-left* margin-left)
  (setq *m5-margin-right* margin-right)
  (setq *m5-bbox-margin* bbox-margin)
  (setq *m5-retry-margin* retry-margin)
  (m5-log (strcat "[CFG] output=" output-dir ", pc3=" pc3 ", ctb=" ctb))
  (princ)
)

(defun module5-run-frame
  (frame-id name xmin ymin xmax ymax paper-w paper-h / bbox retry-bbox ss sel-count dwg-path pdf-path plot-bbox ok-w ok-p)
  (setq bbox (m5-bbox-expand xmin ymin xmax ymax *m5-bbox-margin*))
  (setq ss (m5-select-crossing bbox))
  (if (null ss)
    (progn
      (setq retry-bbox (m5-bbox-expand xmin ymin xmax ymax *m5-retry-margin*))
      (setq ss (m5-select-crossing retry-bbox))
      (if ss
        (setq bbox retry-bbox)
      )
    )
  )

  (if (null ss)
    (progn
      (module5-add-frame-result frame-id "failed" "" "" 0 "CAD_EMPTY_SELECTION")
      (m5-log (strcat "[FRAME] failed empty selection: " frame-id))
    )
    (progn
      (setq sel-count (sslength ss))
      (setq dwg-path (strcat *m5-output-dir* "\\" name ".dwg"))
      (setq pdf-path (strcat *m5-output-dir* "\\" name ".pdf"))
      (setq ok-w (vl-catch-all-apply 'm5-do-wblock (list dwg-path ss)))
      (if (vl-catch-all-error-p ok-w)
        (progn
          (setq *m5-last-wblock-error* (vl-catch-all-error-message ok-w))
          (setq ok-w nil)
        )
      )
      (setq plot-bbox (m5-apply-plot-margins bbox paper-w paper-h))
      (setq ok-p (vl-catch-all-apply 'm5-do-plot (list pdf-path plot-bbox paper-w paper-h)))
      (if (vl-catch-all-error-p ok-p)
        (progn
          (setq *m5-last-plot-error* (vl-catch-all-error-message ok-p))
          (setq ok-p nil)
        )
      )
      (m5-log
        (strcat
          "[FRAME] "
          frame-id
          " wblock="
          (if ok-w "ok" "fail")
          " plot="
          (if ok-p "ok" "fail")
          " wblock_err="
          *m5-last-wblock-error*
          " plot_err="
          *m5-last-plot-error*
          " dwg="
          dwg-path
          " pdf="
          pdf-path
        )
      )
      (if (and ok-w ok-p)
        (progn
          (module5-add-frame-result frame-id "ok" pdf-path dwg-path sel-count "")
          (m5-log (strcat "[FRAME] ok: " frame-id))
        )
        (progn
          (module5-add-frame-result
            frame-id
            "failed"
            pdf-path
            dwg-path
            sel-count
            (if ok-w "PLOT_FAILED" "WBLOCK_FAILED")
          )
          (m5-log (strcat "[FRAME] failed export: " frame-id))
        )
      )
    )
  )
  (princ)
)

(defun module5-run-sheet-set
  (cluster-id name xmin ymin xmax ymax paper-w paper-h page-count / bbox ss sel-count dwg-path pdf-path plot-bbox ok-w ok-p)
  (setq bbox (m5-bbox-expand xmin ymin xmax ymax *m5-bbox-margin*))
  (setq ss (m5-select-crossing bbox))
  (if (null ss)
    (progn
      (setq ss (ssget "_X"))
      (if ss
        (m5-log (strcat "[SHEET] empty crossing, fallback ssget _X: " cluster-id))
      )
    )
  )
  (if (null ss)
    (progn
      (module5-add-sheet-result cluster-id "failed" "" "" page-count "CAD_EMPTY_SELECTION")
      (m5-log (strcat "[SHEET] failed empty selection: " cluster-id))
    )
    (progn
      (setq sel-count (sslength ss))
      (setq dwg-path (strcat *m5-output-dir* "\\" name ".dwg"))
      (setq pdf-path (strcat *m5-output-dir* "\\" name ".pdf"))
      (setq ok-w (vl-catch-all-apply 'm5-do-wblock (list dwg-path ss)))
      (if (vl-catch-all-error-p ok-w)
        (progn
          (setq *m5-last-wblock-error* (vl-catch-all-error-message ok-w))
          (setq ok-w nil)
        )
      )
      (setq plot-bbox (m5-apply-plot-margins bbox paper-w paper-h))
      (setq ok-p (vl-catch-all-apply 'm5-do-plot (list pdf-path plot-bbox paper-w paper-h)))
      (if (vl-catch-all-error-p ok-p)
        (progn
          (setq *m5-last-plot-error* (vl-catch-all-error-message ok-p))
          (setq ok-p nil)
        )
      )
      (m5-log
        (strcat
          "[SHEET] "
          cluster-id
          " wblock="
          (if ok-w "ok" "fail")
          " plot="
          (if ok-p "ok" "fail")
          " wblock_err="
          *m5-last-wblock-error*
          " plot_err="
          *m5-last-plot-error*
          " dwg="
          dwg-path
          " pdf="
          pdf-path
        )
      )
      (if (and ok-w ok-p)
        (progn
          (module5-add-sheet-result cluster-id "ok" pdf-path dwg-path page-count "")
          (m5-log (strcat "[SHEET] ok: " cluster-id ", pages=" (itoa page-count)))
        )
        (progn
          (module5-add-sheet-result
            cluster-id
            "failed"
            pdf-path
            dwg-path
            page-count
            (if ok-w "PLOT_FAILED" "WBLOCK_FAILED")
          )
          (m5-log (strcat "[SHEET] failed export: " cluster-id))
        )
      )
    )
  )
  (princ)
)

(defun module5-finalize ()
  (m5-write-result-json)
  (m5-log "[DONE] module5-finalize")
  (princ)
)

(princ)
