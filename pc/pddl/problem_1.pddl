(define (problem smart-zone-prob-zone1)
  (:domain smart-zone-control)

  (:objects 
    b1 - building
    zone1 - zone
    item1 - item
  )

  (:init
    ;; --- INFRASTRUCTURE ---
    (zone-in-building zone1 b1)

    ;; --- GLOBAL WEATHER ---
    (outdoor-hot)
    (outdoor-raining)

    ;; --- ZONE 1 STATE ---
    
    ;; HVAC: It is cold inside, but hot and raining outside
    (indoor-cold zone1)
    (window-closed zone1)
    (fan-off zone1)
    (heater-off zone1)
    
    ;; Lighting: Someone is there, and it's dark
    (motion-detected zone1)
    (light-low zone1)
    
    ;; Humidity: The air is dry
    (humidity-low zone1)
    
    ;; Delivery: Someone requested item1 to the right side, and they are in the chute
    (delivery-requested-right item1 zone1)
    (product-available item1 zone1)
  )

  (:goal 
    (and 
      ;; 1. HVAC Goal
      (comfortable zone1)
      
      ;; 2. Humidity Goal
      (control-humidity zone1)
      
      ;; 3. Lighting Goal
      (control-lights zone1)
      
      ;; 4. Delivery Goal
      (delivery-request-handled item1 zone1)
    )
  )
)