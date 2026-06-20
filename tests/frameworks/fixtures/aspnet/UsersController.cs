using Microsoft.AspNetCore.Mvc;

namespace Shop.Controllers;

[ApiController]
[Route("api/[controller]")]
public class UsersController : ControllerBase
{
    [HttpGet("{id}")]
    public IActionResult Get(int id)
    {
        return Ok();
    }

    [HttpPost]
    public IActionResult Create()
    {
        return Ok();
    }
}

// a plain service is not a controller -> no routes
public class EmailService
{
    public void Send() { }
}
