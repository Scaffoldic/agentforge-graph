package com.example;

import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class UserController {

    @GetMapping("/users")
    public String list() {
        return "";
    }

    @PostMapping("/users/{id}")
    public String create() {
        return "";
    }

    @RequestMapping(value = "/legacy", method = RequestMethod.PUT)
    public void update() {
    }

    @DeleteMapping
    public void wipe() {
    }
}
