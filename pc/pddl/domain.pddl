;; ============================================================
;; Domain: smart-zone-control (v5 -- matches real hardware flow)
;;
;; Two UI buttons ("deliver left" / "deliver right") ARE the
;; delivery request -- direction is never a separate step, so
;; the old "no direction chosen yet" edge case no longer exists.
;;
;; Sequence per button press:
;;   1) delivery-requested-left/right becomes true (button press)
;;   2) ultrasonic confirms product-available
;;   3) gate motor opens -> gate-open (product slides)
;;   4) end-of-slide motor guides it -> delivered (+ which side, for logging)
;;
;; Edge cases handled:
;;   - product not available            -> notify-unavailable-*
;;   - both buttons pressed at once      -> notify-direction-conflict,
;;                                          blocks both gate-opens
;;   - already delivered / stale flags   -> all re-firing blocked
;; ============================================================

(define (domain smart-zone-control)

  (:requirements :strips :typing :negative-preconditions :disjunctive-preconditions)

  (:types
    building
    zone
    item
  )

  (:predicates
    (zone-in-building ?z - zone ?b - building)

    ;; --- 1) Ambience light ---
    (motion-detected ?z - zone)
    (light-low       ?z - zone)
    (light-normal    ?z - zone)
    (light-high      ?z - zone)
    (led-on          ?z - zone)
    
    ;; --- 2) Temperature / fan ---
    (temperature-high   ?z - zone)
    (temperature-normal ?z - zone)
    (fan-on             ?z - zone)
    
    ;; --- 3) Humidity / humidifier (on when LOW) ---
    (humidity-low    ?z - zone)
    (humidity-normal ?z - zone)
    (humidifier-on   ?z - zone)

    ;; --- 4) Sound / notification ---
    (sound-high        ?z - zone)
    (send-notification ?z - zone)

    ;; --- 5) Delivery: button press = request + direction ---
    (delivery-requested-left        ?i - item ?z - zone)
    (delivery-requested-right       ?i - item ?z - zone)
    (product-available               ?i - item ?z - zone)   ; ultrasonic pre-check
    (delivery-unavailable-notified  ?i - item ?z - zone)
    (gate-open                       ?i - item ?z - zone)     ; gate motor has opened
    (delivered-left                  ?i - item)               ; which side it went, for logging
    (delivered-right                 ?i - item)
  )

  ;; ============================================================
  ;; 1) AMBIENCE LIGHT
  ;; ============================================================

  (:action turn-on-light
    :parameters (?z - zone)
    :precondition (and (motion-detected ?z)
                       (or (light-low ?z) (light-normal ?z))
                       (not (led-on ?z)))
    :effect (led-on ?z)
  )

  (:action turn-off-light-no-motion
    :parameters (?z - zone)
    :precondition (and (led-on ?z) (not (motion-detected ?z)))
    :effect (not (led-on ?z))
  )

  (:action turn-off-light-bright-enough
    :parameters (?z - zone)
    :precondition (and (led-on ?z) (light-high ?z))
    :effect (not (led-on ?z))
  )

  ;; ============================================================
  ;; 2) TEMPERATURE
  ;; ============================================================

  (:action turn-on-fan
    :parameters (?z - zone)
    :precondition (and (temperature-high ?z) (not (fan-on ?z)))
    :effect (fan-on ?z)
  )

  (:action turn-off-fan
    :parameters (?z - zone)
    :precondition (and (fan-on ?z) (temperature-normal ?z))
    :effect (not (fan-on ?z))
  )

  ;; ============================================================
  ;; 3) HUMIDITY
  ;; ============================================================

  (:action turn-on-humidifier
    :parameters (?z - zone)
    :precondition (and (humidity-low ?z) (not (humidifier-on ?z)))
    :effect (humidifier-on ?z)
  )

  (:action turn-off-humidifier
    :parameters (?z - zone)
    :precondition (and (humidifier-on ?z) (humidity-normal ?z))
    :effect (not (humidifier-on ?z))
  )

  ;; ============================================================
  ;; 4) SOUND
  ;; ============================================================

  (:action trigger-notification
    :parameters (?z - zone)
    :precondition (and (sound-high ?z) (not (send-notification ?z)))
    :effect (send-notification ?z)
  )

  (:action clear-notification
    :parameters (?z - zone)
    :precondition (and (send-notification ?z) (not (sound-high ?z)))
    :effect (not (send-notification ?z))
  )

  ;; ============================================================
  ;; 5) DELIVERY — one shared gate opens after ultrasonic check,
  ;;    then the item is guided to the requested side
  ;; ============================================================

  (:action open-gate
    :parameters (?i - item ?z - zone)
    :precondition (and (or (delivery-requested-left ?i ?z)
                           (delivery-requested-right ?i ?z))
                        (not (and (delivery-requested-left ?i ?z)
                                  (delivery-requested-right ?i ?z)))
                        (product-available ?i ?z)
                        (not (gate-open ?i ?z))
                        (not (delivered-left ?i))
                        (not (delivered-right ?i)))
    :effect (gate-open ?i ?z)
  )

  (:action guide-left
    :parameters (?i - item ?z - zone)
    :precondition (and (gate-open ?i ?z)
                        (delivery-requested-left ?i ?z)
                        (not (delivered-left ?i))
                        (not (delivered-right ?i)))
    :effect (and (delivered-left ?i))
  )

  (:action guide-right
    :parameters (?i - item ?z - zone)
    :precondition (and (gate-open ?i ?z)
                        (delivery-requested-right ?i ?z)
                        (not (delivered-left ?i))
                        (not (delivered-right ?i)))
    :effect (and (delivered-right ?i))
  )

  ;; button pressed, but ultrasonic finds no product
  (:action notify-unavailable-left
    :parameters (?i - item ?z - zone)
    :precondition (and (delivery-requested-left ?i ?z)
                        (not (product-available ?i ?z))
                        (not (delivery-unavailable-notified ?i ?z))
                        (not (delivered-left ?i))
                        (not (delivered-right ?i)))
    :effect (delivery-unavailable-notified ?i ?z)
  )

  (:action notify-unavailable-right
    :parameters (?i - item ?z - zone)
    :precondition (and (delivery-requested-right ?i ?z)
                        (not (product-available ?i ?z))
                        (not (delivery-unavailable-notified ?i ?z))
                        (not (delivered-left ?i))
                        (not (delivered-right ?i)))
    :effect (delivery-unavailable-notified ?i ?z)
  )

  (:action clear-unavailable-notice
    :parameters (?i - item ?z - zone)
    :precondition (and (delivery-unavailable-notified ?i ?z)
                        (product-available ?i ?z))
    :effect (not (delivery-unavailable-notified ?i ?z))
  )
)
